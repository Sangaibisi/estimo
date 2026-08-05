"""S12-7 Calibration: every rate on this screen is measured, or it is absent.

The dashboard's own promise (routers/metrics.py module docstring) is the thing most
easily broken by a well-meaning change: a coverage that quietly counts rows it cannot
grade, a per-slice bar drawn from two jobs, a "we beat the baseline" that is one
coin-flip wide. These tests pin the arithmetic AND the refusals.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
from _helpers import make_settings
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from estimo_knowledge import LedgerEntryRow
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from estimo_api.main import create_app

pytestmark = pytest.mark.db

ALEMBIC_INI = Path(__file__).parents[1] / "alembic.ini"


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    url = os.environ["ESTIMO_TEST_DATABASE_URL"]
    os.environ["ESTIMO_DATABASE_URL"] = url
    command.upgrade(Config(str(ALEMBIC_INI)), "head")
    yield url


@pytest.fixture
async def session(database_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as sess:
        await sess.execute(text("TRUNCATE ledger_entries, estimates, runtime_settings CASCADE"))
        await sess.commit()
        yield sess
    await engine.dispose()


@pytest.fixture
async def client(database_url: str, session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(make_settings(database_url))
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


async def _product_row(
    session: AsyncSession,
    *,
    band: tuple[float, float, float] | None = (8, 10, 17),
    actual: float = 12.0,
    team: str | None = None,
    domains: tuple[str, ...] = (),
    completed: dt.date | None = dt.date(2026, 6, 1),
    origin: str | None = None,
) -> LedgerEntryRow:
    row = LedgerEntryRow(
        brd_ref=f"BRD-{uuid.uuid4().hex[:6]}",
        item_title="Fatura üretimi",
        module_tags=["billing-core"],
        domain_tags=list(domains),
        team=team,
        est_optimistic=band[0] if band else None,
        est_likely=band[1] if band else None,
        est_pessimistic=band[2] if band else None,
        estimate_single=None if band else 10,
        actual_effort=actual,
        actual_source="timesheet",
        completed_at=completed,
        origin_ref=origin or f"estimate://{uuid.uuid4()}/WI-1",
    )
    session.add(row)
    await session.commit()
    return row


def _boe_document(
    brd_ref: str,
    title: str,
    band: tuple[float, float, float],
    *,
    answer_uri: str | None = None,
) -> dict[str, object]:
    """A frozen BoE snapshot, built through the real model so a schema change breaks
    these fixtures instead of letting them drift into something the product cannot
    produce."""
    from estimo_core import BoeDocument, EstimateLine, EvidenceRef, ThreePoint

    evidence = [EvidenceRef(kind="ledger", uri=f"ledger://{uuid.uuid4()}")]
    if answer_uri:
        evidence.append(EvidenceRef(kind="answer", uri=answer_uri))
    document = BoeDocument(
        brd_ref=brd_ref,
        title=title,
        cone_stage="approved_scope",
        lines=(
            EstimateLine(
                work_item_id="WI-1",
                range=ThreePoint(optimistic=band[0], likely=band[1], pessimistic=band[2]),
                confidence="medium",
                evidence=tuple(evidence),
            ),
        ),
    )
    # `exclude={"total"}` mirrors what build_boe stores: `total` is a computed field,
    # and a dump that carries it cannot be re-validated (BoeDocument forbids extras).
    return document.model_dump(mode="json", exclude={"total"})


async def test_a_connector_row_is_not_graded_as_a_pipeline_estimate(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """`origin_ref IS NOT NULL` also matches the Jira connector's `jira://` rows.

    Those carry a single number and no band, so every one of them is an automatic
    coverage miss — the pipeline scored for estimates it never made.
    """
    await _product_row(session, band=(8, 10, 17), actual=12.0)
    # Banded on purpose: an unbanded row is already excluded by the coverage rule, so
    # a single-number fixture would let this test pass with the predicate removed.
    await _product_row(session, band=(1, 2, 3), actual=40.0, origin="jira://ACME-42")

    accuracy = (await client.get("/v1/metrics/overview")).json()["product_accuracy"]
    assert accuracy["samples"] == 1, "a connector row was graded as a pipeline estimate"


async def test_a_row_without_a_band_is_counted_apart_not_as_a_miss(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """A single-number row is not a failed range — it is not a range."""
    await _product_row(session, band=(8, 10, 17), actual=12.0)
    await _product_row(session, band=None, actual=40.0)

    accuracy = (await client.get("/v1/metrics/overview")).json()["product_accuracy"]
    assert accuracy["samples"] == 1, "an ungraded row entered the denominator"
    assert accuracy["unbanded"] == 1


async def test_a_slice_below_the_sample_floor_is_withheld_not_drawn(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """A bar drawn from three jobs is a point estimate wearing a rate's clothes."""
    for _ in range(3):
        await _product_row(session, team="squad-billing", actual=12.0)

    slices = (await client.get("/v1/metrics/overview")).json()["slices"]
    billing = next(entry for entry in slices["teams"] if entry["key"] == "squad-billing")
    assert billing["samples"] == 3
    assert billing["enough"] is False
    assert billing["coverage"] is None, "a 3-sample slice was rendered as a rate"


async def test_a_slice_at_the_floor_is_reported(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    from estimo_estimate.calibration import MIN_SAMPLES

    for index in range(MIN_SAMPLES):
        # One of them misses the band, so the rate is not a trivial 1.0.
        await _product_row(session, team="squad-billing", actual=12.0 if index else 99.0)

    slices = (await client.get("/v1/metrics/overview")).json()["slices"]
    billing = next(entry for entry in slices["teams"] if entry["key"] == "squad-billing")
    assert billing["enough"] is True
    assert billing["coverage"] == round((MIN_SAMPLES - 1) / MIN_SAMPLES, 3)


async def test_the_time_window_excludes_rows_that_never_said_when_they_finished(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """ "No rows in the last 24 months" and "no row says when it finished" are
    different facts, and a window that silently keeps undated rows tells neither."""
    await _product_row(session, completed=dt.date(2026, 6, 1), actual=12.0)
    await _product_row(session, completed=dt.date(2019, 1, 1), actual=12.0)
    await _product_row(session, completed=None, actual=12.0)

    everything = (await client.get("/v1/metrics/overview")).json()["product_accuracy"]
    assert everything["samples"] == 3

    windowed = (await client.get("/v1/metrics/overview", params={"months": 24})).json()
    assert windowed["product_accuracy"]["samples"] == 1
    assert windowed["window"]["months"] == 24


async def test_a_team_slice_narrows_the_headline(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _product_row(session, team="squad-billing", actual=12.0)
    await _product_row(session, team="squad-crm", actual=99.0)

    sliced = (await client.get("/v1/metrics/overview", params={"team": "squad-billing"})).json()
    assert sliced["product_accuracy"]["samples"] == 1
    assert sliced["window"]["team"] == "squad-billing"


async def test_a_one_sided_win_over_two_items_is_not_reported_as_a_win(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """The design says "on this dataset the difference is not meaningful" — which is a
    claim about a test, not a feeling. Two items cannot distinguish anything: the
    two-sided sign test's smallest possible p at n=2 is 0.5.
    """
    await _product_row(session, band=(8, 10, 12), actual=10.0)
    await _product_row(session, band=(8, 10, 12), actual=11.0)

    comparison = (await client.get("/v1/metrics/overview")).json()["product_accuracy"]["comparison"]
    assert comparison["verdict"] == "not-distinguishable"
    assert comparison["p_value"] is not None and comparison["p_value"] > 0.05


async def test_mape_excludes_items_too_small_to_have_a_percentage(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """A half-day miss on a 1 pd item is 50%, and one such item drags the mean more
    than ten honest ones. Excluded and COUNTED, never silently averaged in."""
    await _product_row(session, band=(8, 10, 17), actual=12.0)
    await _product_row(session, band=(0.5, 1, 2), actual=0.5)

    accuracy = (await client.get("/v1/metrics/overview")).json()["product_accuracy"]
    assert accuracy["mape_excluded"] == 1
    # 10 estimated vs 12 actual -> 2/12
    assert accuracy["mape_product"] == round(2 / 12, 3)


async def test_the_dashboard_says_when_it_has_nothing_to_say(
    client: httpx.AsyncClient,
) -> None:
    """An empty deployment must return nulls with sample counts, not zeros. A 0%
    coverage reads as "our ranges never hold"; absent reads as "we have not measured
    yet", and only one of those is true on day one."""
    body = (await client.get("/v1/metrics/overview")).json()
    assert body["product_accuracy"]["coverage"] is None
    assert body["product_accuracy"]["samples"] == 0
    assert body["product_accuracy"]["comparison"]["verdict"] == "no-signal"
    assert body["slices"]["teams"] == []
    assert body["question_impact"]["changed_share"] is None
    assert body["calibration"]["current"]["rolling_coverage"] is None
    assert body["calibration"]["current"]["rolling_samples"] == 0


async def test_the_headline_rate_is_withheld_on_a_thin_slice(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """The floor has to apply to the HEADLINE, not just the per-slice bars.

    Before the screen could be sliced, the headline was the whole corpus and a thin one
    was obvious. Now a reader picks a domain from a dropdown, lands on one closed job,
    and the chip reads "we captured actuals inside the range 0% of the time" — a
    sentence about a single item, printed as a verdict on the product.
    """
    from estimo_estimate.calibration import MIN_SAMPLES

    await _product_row(session, domains=("crm",), actual=99.0)

    thin = (await client.get("/v1/metrics/overview", params={"domain": "crm"})).json()
    assert thin["product_accuracy"]["samples"] == 1
    assert thin["product_accuracy"]["enough"] is False
    assert thin["product_accuracy"]["coverage"] is None, "a 1-row slice was published as a rate"

    for _ in range(MIN_SAMPLES - 1):
        await _product_row(session, domains=("crm",), actual=12.0)
    full = (await client.get("/v1/metrics/overview", params={"domain": "crm"})).json()
    assert full["product_accuracy"]["enough"] is True
    assert full["product_accuracy"]["coverage"] == round((MIN_SAMPLES - 1) / MIN_SAMPLES, 3)


async def test_the_sign_test_survives_a_thousand_completed_items(
    client: httpx.AsyncClient,
) -> None:
    """The naive formula raises OverflowError at 1024 decided pairs.

    That is not an exotic input — it is a tenant that has completed a thousand items,
    i.e. the success case, and it took the whole dashboard down with it (every other
    panel is built in the same dict). Checked at the function, because seeding 1024
    ledger rows per test run costs more than the bug does.
    """
    from estimo_api.routers.metrics import _paired_verdict

    verdict = _paired_verdict([1.0] * 1024, [2.0] * 1024)
    assert verdict["verdict"] == "pipeline-better"
    # Never the impossible literal 0: an exact p of 3e-9 is not "p = 0".
    assert verdict["p_value"] == 0.0001
    assert verdict["p_value_is_upper_bound"] is True

    huge = _paired_verdict([1.0] * 5000, [2.0] * 5000)
    assert huge["p_value"] == 0.0001, "a log-space underflow reached the screen as 0"


async def test_a_slice_says_whether_it_is_a_team_or_a_domain(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """Team and domain are both free text normalized at the same import boundary, so
    "billing" can be both — and two rows labelled identically are two different
    claims about two different populations."""
    await _product_row(session, team="billing", domains=("billing",), actual=12.0)

    slices = (await client.get("/v1/metrics/overview")).json()["slices"]
    assert [entry["kind"] for entry in slices["teams"]] == ["team"]
    assert [entry["kind"] for entry in slices["domains"]] == ["domain"]


async def test_the_question_panel_withholds_an_unsigned_draft(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """`GET /{id}/versions` refuses to disclose even the DIRECTION a line moved for a
    version that is not fully signed, because a line's three points scale with the same
    analog median. This screen is reachable by a reviewer — the exact role that gate
    applies to — so an aggregate over unsigned drafts is a bypass of it, not an
    exception to it."""
    import uuid as _uuid

    from estimo_api.estimates_models import BoeVersionRow, EstimateRecord

    estimate_id = _uuid.uuid4()
    session.add(
        EstimateRecord(
            id=estimate_id,
            brd_ref="BRD-Q",
            title="Question impact",
            status="boe_draft",
            state={"source_path": "x.docx", "status": "ready_for_estimation"},
            boe_version=2,
        )
    )
    await session.flush()
    for version, band in ((1, (4.0, 10.0, 20.0)), (2, (8.0, 10.0, 12.0))):
        session.add(
            BoeVersionRow(
                estimate_id=estimate_id,
                version=version,
                document=_boe_document(
                    "BRD-Q",
                    "Question impact",
                    band,
                    answer_uri="answer://Q-REQ-1" if version == 2 else None,
                ),
            )
        )
    await session.commit()

    impact = (await client.get("/v1/metrics/overview")).json()["question_impact"]
    assert impact["samples"] == 0, "an unsigned draft's diff reached the dashboard"
    assert impact["changed_share"] is None


async def test_a_band_recorded_after_an_earlier_version_was_signed_is_not_blind(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """A rebuild drops the signatures, so "is the current draft fully signed" answers
    the wrong question: someone who read v1 after it was signed and then typed a band
    against v2 has seen the numbers. What decides this is the estimate's history."""
    import uuid as _uuid

    from estimo_api.estimates_models import EstimateRecord, IndependentEstimate, LineSignature

    estimate_id = _uuid.uuid4()
    boe = _boe_document("BRD-B", "Blind", (8.0, 10.0, 17.0))
    session.add(
        EstimateRecord(
            id=estimate_id,
            brd_ref="BRD-B",
            title="Blind",
            status="boe_draft",
            state={
                "source_path": "x.docx",
                "status": "ready_for_estimation",
                "work_items": [
                    {
                        "id": "WI-1",
                        "brd_ref": "BRD-B",
                        "title": "Fatura üretimi",
                        "requirement_ids": ["REQ-1"],
                    }
                ],
            },
            boe=boe,
            boe_version=2,
        )
    )
    await session.flush()
    from estimo_api.estimates_models import BoeVersionRow

    for version in (1, 2):
        session.add(BoeVersionRow(estimate_id=estimate_id, version=version, document=boe))
    # v1 was fully signed — the document was readable through GET /{id} and /boe.docx.
    session.add(
        LineSignature(
            estimate_id=estimate_id,
            work_item_id="WI-1",
            boe_version=1,
            name="reviewer",
            role="reviewer",
        )
    )
    await session.commit()

    recorded = await client.post(
        f"/v1/estimates/{estimate_id}/independent",
        json={
            "work_item_id": "WI-1",
            "estimator": "late-comer",
            "optimistic": 8,
            "likely": 10,
            "pessimistic": 17,
        },
    )
    assert recorded.status_code == 201, recorded.text
    band = (
        await session.execute(
            select(IndependentEstimate).where(IndependentEstimate.estimate_id == estimate_id)
        )
    ).scalar_one()
    await session.refresh(band)
    assert band.blind is False, "a band typed after a signed version was counted as blind"

    entry = (await client.get("/v1/metrics/overview")).json()["anchoring"]["entry"]
    assert entry["after_readable"] == 1
    assert entry["blind"] == 0
