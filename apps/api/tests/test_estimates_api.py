"""S7 backend: the estimate workflow API, with server-enforced independent-first."""

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
from _helpers import make_settings
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from estimo_api.main import create_app

pytestmark = pytest.mark.db

REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = Path(__file__).parents[1] / "alembic.ini"
FIXTURES = REPO_ROOT / "fixtures" / "brd"
SEED = REPO_ROOT / "fixtures" / "seed" / "sample-seed.csv"


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    url = os.environ["ESTIMO_TEST_DATABASE_URL"]
    os.environ["ESTIMO_DATABASE_URL"] = url
    command.upgrade(Config(str(ALEMBIC_INI)), "head")
    yield url


@pytest.fixture
async def client(database_url: str) -> AsyncIterator[httpx.AsyncClient]:
    engine = create_async_engine(database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        await session.execute(
            text(
                "TRUNCATE estimates, ledger_entries, knowledge_chunks, "
                "calibration_snapshots CASCADE"
            )
        )
        await session.commit()
        from estimo_knowledge import import_seed

        await import_seed(session, SEED)
    await engine.dispose()

    app = create_app(make_settings(database_url))
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


async def _upload(client: httpx.AsyncClient, name: str) -> dict[str, object]:
    path = FIXTURES / name
    response = await client.post(
        "/v1/estimates",
        files={
            "file": (
                name,
                path.read_bytes(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


async def _record_band(
    client: httpx.AsyncClient, estimate_id: object, item_id: str, estimator: str
) -> httpx.Response:
    return await client.post(
        f"/v1/estimates/{estimate_id}/independent",
        json={
            "work_item_id": item_id,
            "estimator": estimator,
            "optimistic": 5,
            "likely": 8,
            "pessimistic": 13,
        },
    )


async def test_full_workflow_clean_brd(client: httpx.AsyncClient) -> None:
    summary = await _upload(client, "BRD-AUR-26-02-konsolide-fatura.docx")
    assert summary["status"] == "ready_for_estimation"
    assert summary["work_items"] == 6
    estimate_id = summary["id"]

    built = await client.post(f"/v1/estimates/{estimate_id}/estimate")
    assert built.status_code == 200
    assert built.json()["critic"] == []
    # Independent-first is surface-wide: the build response carries NO band content,
    # and GET withholds the draft body until full sign-off.
    assert "boe" not in built.json()
    detail = (await client.get(f"/v1/estimates/{estimate_id}")).json()
    assert detail["boe"] is None
    assert detail["fully_signed"] is False
    assert detail["summary"]["has_boe"] is True

    rebuild = await client.post(f"/v1/estimates/{estimate_id}/estimate")
    assert rebuild.status_code == 409  # no silent re-draft over a live draft

    # Independent-first: no AI band before the estimator's own band exists.
    desk = (
        await client.get(f"/v1/estimates/{estimate_id}/desk", params={"estimator": "D. Aksoy"})
    ).json()
    first_item = desk["items"][0]
    assert first_item["ai"] is None
    item_id = first_item["work_item"]["id"]

    # Signing requires the signer's own revealed band — not just a name.
    premature_sign = await client.post(
        f"/v1/estimates/{estimate_id}/sign",
        json={"work_item_id": item_id, "name": "D. Aksoy", "role": "Reviewer"},
    )
    assert premature_sign.status_code == 409

    recorded = await _record_band(client, estimate_id, item_id, "D. Aksoy")
    assert recorded.status_code == 201

    duplicate = await client.post(
        f"/v1/estimates/{estimate_id}/independent",
        json={
            "work_item_id": item_id,
            "estimator": "D. Aksoy",
            "optimistic": 1,
            "likely": 2,
            "pessimistic": 3,
        },
    )
    assert duplicate.status_code == 409  # immutable: anchoring telemetry integrity

    desk = (
        await client.get(f"/v1/estimates/{estimate_id}/desk", params={"estimator": "D. Aksoy"})
    ).json()
    revealed = next(i for i in desk["items"] if i["work_item"]["id"] == item_id)
    assert revealed["ai"] is not None
    assert revealed["delta_likely"] is not None
    others = [i for i in desk["items"] if i["work_item"]["id"] != item_id]
    assert all(i["ai"] is None for i in others)  # reveal is per item, per estimator

    # The .docx export contains every band, so it stays locked until all lines signed.
    locked = await client.get(f"/v1/estimates/{estimate_id}/boe.docx")
    assert locked.status_code == 409

    for item in desk["items"]:
        wid = item["work_item"]["id"]
        if wid != item_id:
            assert (await _record_band(client, estimate_id, wid, "D. Aksoy")).status_code == 201
        signed = await client.post(
            f"/v1/estimates/{estimate_id}/sign",
            json={"work_item_id": wid, "name": "D. Aksoy", "role": "Reviewer"},
        )
        assert signed.status_code == 201

    detail = (await client.get(f"/v1/estimates/{estimate_id}")).json()
    assert detail["fully_signed"] is True
    assert detail["boe"] is not None  # full sign-off unlocks the draft body

    docx = await client.get(f"/v1/estimates/{estimate_id}/boe.docx")
    assert docx.status_code == 200
    assert docx.content[:2] == b"PK"  # a zip container => real .docx
    disposition = docx.headers["content-disposition"]
    assert "filename=" in disposition and "filename*=UTF-8''" in disposition
    assert "\n" not in disposition and "\r" not in disposition

    # S8-1: an actual closes the loop — ledger row + feedback + calibration snapshot.
    actual = await client.post(
        f"/v1/estimates/{estimate_id}/actuals",
        json={"work_item_id": item_id, "actual_effort": 9, "actual_source": "timesheet"},
    )
    assert actual.status_code == 201
    assert actual.json()["deviation"] is not None

    listed = (await client.get(f"/v1/estimates/{estimate_id}/actuals")).json()
    assert len(listed) == 1
    assert listed[0]["work_item_id"] == item_id
    assert listed[0]["actual_effort"] == 9

    # S8-3: the dashboard overview reflects the loop.
    overview = (await client.get("/v1/metrics/overview")).json()
    assert overview["product_accuracy"]["samples"] >= 1
    assert overview["calibration"]["current"]["samples"] >= 0
    assert overview["calibration"]["series"], "actual must have snapshotted calibration"
    assert overview["anchoring"]["samples"] >= 1  # desk reveals logged deltas
    assert overview["workflow"]["estimates"] >= 1


async def test_answers_flow_and_boe_invalidation(client: httpx.AsyncClient) -> None:
    summary = await _upload(client, "BRD-AUR-26-01-taksitlendirme.docx")
    assert summary["status"] == "awaiting_answers"
    estimate_id = summary["id"]

    premature = await client.post(f"/v1/estimates/{estimate_id}/estimate")
    assert premature.status_code == 409  # PRINCIPLES #3 at the API boundary

    answered = await client.post(
        f"/v1/estimates/{estimate_id}/answers",
        json={
            "answers": {
                "Q-REQ-G-04": (
                    "Kurumsal müşterilerde taksit sayısı 6 ile sınırlıdır ve komisyon "
                    "oranı %5 sabittir."
                )
            }
        },
    )
    assert answered.status_code == 200
    assert answered.json()["status"] == "ready_for_estimation"

    unknown = await client.post(
        f"/v1/estimates/{estimate_id}/answers", json={"answers": {"Q-TYPO": "x" * 30}}
    )
    assert unknown.status_code == 422


async def test_empty_answer_does_not_close_question(client: httpx.AsyncClient) -> None:
    summary = await _upload(client, "BRD-AUR-26-01-taksitlendirme.docx")
    estimate_id = summary["id"]
    assert summary["open_questions"] == 1

    empty = await client.post(
        f"/v1/estimates/{estimate_id}/answers", json={"answers": {"Q-REQ-G-04": "   "}}
    )
    assert empty.status_code == 422  # an empty answer is "no answer"

    detail = (await client.get(f"/v1/estimates/{estimate_id}")).json()
    assert detail["summary"]["open_questions"] == 1  # the question stays open


async def test_rebuild_invalidates_stale_reveals_and_signatures(
    client: httpx.AsyncClient,
) -> None:
    """A rebuilt draft must not inherit reveals or sign-offs from a dead draft."""
    summary = await _upload(client, "BRD-AUR-26-01-taksitlendirme.docx")
    estimate_id = summary["id"]

    answered = await client.post(
        f"/v1/estimates/{estimate_id}/answers",
        json={"answers": {"Q-REQ-G-04": "Kurumsal segmentte taksit sayısı 6 ile sınırlıdır."}},
    )
    assert answered.status_code == 200
    assert (await client.post(f"/v1/estimates/{estimate_id}/estimate")).status_code == 200

    desk = (
        await client.get(f"/v1/estimates/{estimate_id}/desk", params={"estimator": "B. Tan"})
    ).json()
    item_id = desk["items"][0]["work_item"]["id"]
    assert (await _record_band(client, estimate_id, item_id, "B. Tan")).status_code == 201
    signed = await client.post(
        f"/v1/estimates/{estimate_id}/sign",
        json={"work_item_id": item_id, "name": "B. Tan", "role": "Reviewer"},
    )
    assert signed.status_code == 201

    # A revised answer arrives: it invalidates the standing draft, after which a
    # fresh build is allowed.
    reanswer = await client.post(
        f"/v1/estimates/{estimate_id}/answers",
        json={
            "answers": {
                "Q-REQ-G-04": (
                    "Revize karar: kurumsal segmentte taksit sayısı 9 olarak onaylandı; "
                    "peşinat %20 zorunludur."
                )
            }
        },
    )
    assert reanswer.status_code == 200  # invalidates the draft
    assert (await client.post(f"/v1/estimates/{estimate_id}/estimate")).status_code == 200

    # The old independent band and signature are stamped with the dead version:
    # nothing about the new draft is revealed or signed.
    desk = (
        await client.get(f"/v1/estimates/{estimate_id}/desk", params={"estimator": "B. Tan"})
    ).json()
    entry = next(i for i in desk["items"] if i["work_item"]["id"] == item_id)
    assert entry["independent"] is None
    assert entry["ai"] is None
    assert entry["signed"] is False

    # Re-recording against the new draft works (no unique-constraint collision) and
    # reveals with fresh telemetry.
    assert (await _record_band(client, estimate_id, item_id, "B. Tan")).status_code == 201
    desk = (
        await client.get(f"/v1/estimates/{estimate_id}/desk", params={"estimator": "B. Tan"})
    ).json()
    entry = next(i for i in desk["items"] if i["work_item"]["id"] == item_id)
    assert entry["ai"] is not None


async def test_upload_rejects_non_docx(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/estimates", files={"file": ("brd.txt", b"plain", "text/plain")}
    )
    assert response.status_code == 422


async def test_upload_size_limit_enforced_while_streaming(client: httpx.AsyncClient) -> None:
    import estimo_api.routers.estimates as estimates_module

    original = estimates_module.MAX_UPLOAD_BYTES
    estimates_module.MAX_UPLOAD_BYTES = 1024
    try:
        response = await client.post(
            "/v1/estimates",
            files={
                "file": (
                    "big.docx",
                    b"x" * 4096,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        assert response.status_code == 413
    finally:
        estimates_module.MAX_UPLOAD_BYTES = original


async def test_event_capture(client: httpx.AsyncClient) -> None:
    summary = await _upload(client, "BRD-AUR-26-04-bakiye-tasima.docx")
    response = await client.post(
        f"/v1/estimates/{summary['id']}/events",
        json={"kind": "section-edit", "payload": {"section": "assumptions", "distance": 12}},
    )
    assert response.status_code == 201

    for reserved in ("draft-revealed", "independent-recorded", "actual-recorded"):
        forged = await client.post(
            f"/v1/estimates/{summary['id']}/events",
            json={"kind": reserved, "payload": {"work_item_id": "WI-X"}},
        )
        assert forged.status_code == 422  # server-reserved kinds are not forgeable


async def test_actuals_require_fully_signed_estimate(client: httpx.AsyncClient) -> None:
    summary = await _upload(client, "BRD-AUR-26-02-konsolide-fatura.docx")
    estimate_id = summary["id"]
    assert (await client.post(f"/v1/estimates/{estimate_id}/estimate")).status_code == 200
    desk = (
        await client.get(f"/v1/estimates/{estimate_id}/desk", params={"estimator": "E. Kaya"})
    ).json()
    item_id = desk["items"][0]["work_item"]["id"]
    response = await client.post(
        f"/v1/estimates/{estimate_id}/actuals",
        json={"work_item_id": item_id, "actual_effort": 5, "actual_source": "timesheet"},
    )
    assert response.status_code == 409  # actuals attach to the signed estimate of record


def test_telemetry_forwards_metadata_only() -> None:
    """The privacy boundary is enforced at the forwarder, not assumed of callers:
    free text (BRD/prompt bodies) must never leave the process."""
    from estimo_api.telemetry import sanitize_metadata

    clean = sanitize_metadata(
        {
            "work_item_id": "WI-G-01",
            "actual_source": "timesheet",
            "delta_likely": -2.1,
            "scope_changed": True,
            "text": "Müşteri, çağrı merkezi üzerinden konsolide fatura talebinde bulunabilmelidir.",
            "estimator": "D. Aksoy",
            "nested": {"anything": 1},
        }
    )
    assert clean == {
        "work_item_id": "WI-G-01",
        "actual_source": "timesheet",
        "delta_likely": -2.1,
        "scope_changed": True,
    }


async def test_event_payload_size_capped(client: httpx.AsyncClient) -> None:
    summary = await _upload(client, "BRD-AUR-26-04-bakiye-tasima.docx")
    oversized = await client.post(
        f"/v1/estimates/{summary['id']}/events",
        json={"kind": "section-edit", "payload": {"blob": "x" * 5000}},
    )
    assert oversized.status_code == 422


def test_telemetry_is_noop_without_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from estimo_api import telemetry

    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    telemetry.reset_cached_client()
    try:
        assert telemetry.emit_event("section-edit", "x", {"a": 1}) is False
        assert telemetry.emit_score("anchoring-delta-likely", 1.5, "x") is False
    finally:
        telemetry.reset_cached_client()


def test_independent_unique_constraint_exists_on_model() -> None:
    """Guards model/migration drift: the race backstop must live in BOTH places."""
    from sqlalchemy import Table

    from estimo_api.estimates_models import IndependentEstimate

    table = IndependentEstimate.__table__
    assert isinstance(table, Table)
    names = {constraint.name for constraint in table.constraints}
    assert "uq_independent_estimates_item_estimator_version" in names


async def test_exported_docx_names_its_signers(client: httpx.AsyncClient) -> None:
    """PRINCIPLES #9: the signature trail must ship INSIDE the exported artefact —
    a blank signature table would make the document unusable as a record."""
    import io
    import zipfile

    summary = await _upload(client, "BRD-AUR-26-02-konsolide-fatura.docx")
    estimate_id = summary["id"]
    assert (await client.post(f"/v1/estimates/{estimate_id}/estimate")).status_code == 200

    desk = (
        await client.get(f"/v1/estimates/{estimate_id}/desk", params={"estimator": "M. Yılmaz"})
    ).json()
    for item in desk["items"]:
        wid = item["work_item"]["id"]
        assert (await _record_band(client, estimate_id, wid, "M. Yılmaz")).status_code == 201
        signed = await client.post(
            f"/v1/estimates/{estimate_id}/sign",
            json={"work_item_id": wid, "name": "M. Yılmaz", "role": "Delivery Manager"},
        )
        assert signed.status_code == 201

    docx = await client.get(f"/v1/estimates/{estimate_id}/boe.docx")
    assert docx.status_code == 200
    with zipfile.ZipFile(io.BytesIO(docx.content)) as archive:
        document = archive.read("word/document.xml").decode("utf-8")
    assert "M. Yılmaz" in document, "the signer is missing from the exported document"
    assert "Delivery Manager" in document
