"""S12-6 Ledger: slices, measured similarity, and the seed-set import wizard.

Two claims this screen makes that could quietly become false:

- a **similarity percentage**, which must come from a measurement and never from a
  rank (a fused RRF score is ordinal — printing it as a percentage would invent a
  figure on the one screen whose entire argument is that its numbers are real);
- a **slice**, which must narrow retrieval rather than its output, or a reader who
  filters by team sees three matches where the ledger holds forty.

Plus the import gate: the privacy checklist is the only moment anyone asserts that a
file about to become permanent vendor memory carries no personal data (SECURITY.md),
so it is enforced server-side.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
import respx
from _helpers import make_settings
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from estimo_knowledge import LedgerEntryRow
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from estimo_api.main import create_app

pytestmark = pytest.mark.db

ALEMBIC_INI = __import__("pathlib").Path(__file__).parents[1] / "alembic.ini"

CSV_HEADER = (
    "brd_ref;kalem;modüller;alan;takım;iyimser;olası;kötümser;"
    "gerçekleşen;gerçekleşme kaynağı;bitiş tarihi"
)


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
        await sess.execute(text("TRUNCATE ledger_entries, estimates CASCADE"))
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


async def _add(
    session: AsyncSession,
    *,
    title: str,
    team: str | None = None,
    domains: tuple[str, ...] = (),
    actual: float | None = 12.0,
    origin_ref: str | None = None,
) -> LedgerEntryRow:
    row = LedgerEntryRow(
        brd_ref=f"BRD-{uuid.uuid4().hex[:6]}",
        item_title=title,
        module_tags=["billing-core"],
        domain_tags=list(domains),
        team=team,
        est_optimistic=8,
        est_likely=10,
        est_pessimistic=17,
        actual_effort=actual,
        completed_at=dt.date(2024, 3, 15),
        origin_ref=origin_ref,
    )
    session.add(row)
    await session.commit()
    return row


async def test_a_team_slice_narrows_retrieval_not_its_output(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """The whole reason the slice lives in SQL.

    The charging row matches both query concepts and therefore outranks the billing
    row. Ask for the top ONE match within the billing slice: a slice applied to
    retrieval returns the billing row, a slice applied to retrieval's OUTPUT returns
    nothing at all — the reader concludes their team has never done this work.
    """
    await _add(session, title="Konsolide fatura kampanya raporu", team="charging")
    billing = await _add(session, title="Konsolide fatura üretimi", team="billing")

    response = await client.get("/v1/ledger", params={"q": "fatura kampanya", "limit": 1})
    assert response.status_code == 200, response.text
    assert [e["team"] for e in response.json()["entries"]] == ["charging"], "ranking assumption"

    sliced = await client.get(
        "/v1/ledger", params={"q": "fatura kampanya", "team": "billing", "limit": 1}
    )
    assert sliced.status_code == 200, sliced.text
    body = sliced.json()
    assert [e["id"] for e in body["entries"]] == [str(billing.id)]
    assert body["sliced"] is True
    # The counts describe the slice too, or "1 of 212" would compare a filtered list
    # against an unfiltered universe.
    assert body["total"] == 1


async def test_a_domain_slice_matches_on_tags(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _add(session, title="Fatura üretimi", domains=("charging",))
    tagged = await _add(session, title="Fatura arşivi", domains=("billing", "archive"))

    response = await client.get("/v1/ledger", params={"domain": "billing"})
    body = response.json()
    assert [e["id"] for e in body["entries"]] == [str(tagged.id)]
    assert body["facets"]["domains"] == ["archive", "billing", "charging"]


async def test_similarity_is_absent_when_nothing_measured_it(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """No dense leg, no percentage.

    The test settings point at an unreachable gateway, so the embedding call fails and
    retrieval degrades to lexical. Two things must hold: the screen still answers, and
    every similarity is null. A rank-derived percentage would be non-null here — that
    is the mutation this pins.
    """
    await _add(session, title="Konsolide fatura üretimi")

    response = await client.get("/v1/ledger", params={"q": "fatura"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["entries"], "the lexical leg still has to answer"
    assert {e["similarity"] for e in body["entries"]} == {None}
    assert body["retrieval"] == "lexical"


async def test_only_product_written_rows_link_back_to_a_boe_row(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    estimate_id = uuid.uuid4()
    await _add(session, title="İmported satır")
    await _add(
        session,
        title="Ürün satırı",
        origin_ref=f"estimate://{estimate_id}/WI-3",
    )

    entries = (await client.get("/v1/ledger")).json()["entries"]
    links = {e["item_title"]: e["boe_link"] for e in entries}
    assert links["İmported satır"] is None
    assert links["Ürün satırı"] == {"estimate_id": str(estimate_id), "work_item_id": "WI-3"}


def _csv(*rows: str) -> bytes:
    return ("\n".join((CSV_HEADER, *rows))).encode("utf-8")


def _files(payload: bytes, name: str = "seed.csv") -> dict[str, Any]:
    return {"file": (name, payload, "text/csv")}


async def test_the_privacy_checklist_is_enforced_by_the_server(
    client: httpx.AsyncClient,
) -> None:
    """A browser-only checkbox is a decoration, not an assertion."""
    payload = _csv(
        "BRD-1;Fatura üretimi;billing-core;billing;billing;8;10;17;12;timesheet;15.03.2024"
    )

    refused = await client.post("/v1/ledger/import", files=_files(payload))
    assert refused.status_code == 400
    assert "checklist" in refused.json()["detail"]
    assert (await client.get("/v1/ledger")).json()["total"] == 0, "a refused import wrote rows"

    accepted = await client.post(
        "/v1/ledger/import", files=_files(payload), data={"acknowledged": "true"}
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["imported"] == 1
    assert (await client.get("/v1/ledger")).json()["total"] == 1


async def test_preview_proposes_a_mapping_and_writes_nothing(
    client: httpx.AsyncClient,
) -> None:
    payload = _csv(
        "BRD-1;Fatura üretimi;billing-core;billing;billing;8;10;17;12;timesheet;15.03.2024"
    )

    response = await client.post("/v1/ledger/import/preview", files=_files(payload))
    assert response.status_code == 200, response.text
    body = response.json()
    mapping = {column["header"]: column["field"] for column in body["columns"]}
    assert mapping["kalem"] == "item_title"
    assert mapping["gerçekleşen"] == "actual_effort"
    assert body["rows"] == 1
    assert body["missing_required"] == []
    # A sample value per column — the operator cannot certify "no personal data in
    # free-text fields" against column names alone.
    assert next(c["sample"] for c in body["columns"] if c["header"] == "kalem") == "Fatura üretimi"
    assert (await client.get("/v1/ledger")).json()["total"] == 0, "preview imported rows"


async def test_preview_names_the_columns_it_could_not_place(
    client: httpx.AsyncClient,
) -> None:
    payload = ("brd_ref;kalem;serbest not\nBRD-1;Fatura üretimi;bir şey").encode()

    body = (await client.post("/v1/ledger/import/preview", files=_files(payload))).json()
    unmapped = [c["header"] for c in body["columns"] if c["field"] is None]
    assert unmapped == ["serbest not"]


async def test_a_column_left_unmapped_is_not_imported_by_alias(
    client: httpx.AsyncClient,
) -> None:
    """A confirmed mapping is the whole contract.

    The operator dropped `takım` in the wizard. If the importer kept an alias
    fallback underneath the mapping, the column would come back by name coincidence —
    importing data somebody deliberately excluded.
    """
    payload = _csv(
        "BRD-1;Fatura üretimi;billing-core;billing;billing;8;10;17;12;timesheet;15.03.2024"
    )
    mapping = (
        '{"brd_ref": "brd_ref", "kalem": "item_title", "olası": "est_likely",'
        ' "gerçekleşen": "actual_effort", "gerçekleşme kaynağı": "actual_source"}'
    )

    response = await client.post(
        "/v1/ledger/import",
        files=_files(payload),
        data={"acknowledged": "true", "mapping": mapping},
    )
    assert response.status_code == 200, response.text
    assert response.json()["rejected"] == []
    entry = (await client.get("/v1/ledger")).json()["entries"][0]
    assert entry["team"] is None
    assert entry["actual_effort"] == 12.0


async def test_bad_rows_queue_up_while_good_rows_import(client: httpx.AsyncClient) -> None:
    payload = _csv(
        "BRD-1;Fatura üretimi;billing-core;billing;billing;8;10;17;12;timesheet;15.03.2024",
        ";;billing-core;billing;billing;8;10;17;12;timesheet;15.03.2024",
        "BRD-3;Arşiv;billing-core;billing;billing;8;10;17;;;",
    )

    report = (
        await client.post("/v1/ledger/import", files=_files(payload), data={"acknowledged": "true"})
    ).json()
    assert report["total_rows"] == 3
    assert report["imported"] == 2
    assert [row["row"] for row in report["rejected"]] == [3]
    # Imported, not rejected: an estimate whose actual has not landed is still a true
    # record — but it cannot answer this ledger's question, so it is counted apart.
    assert report["without_actuals"] == 1
    assert (await client.get("/v1/ledger")).json()["with_actuals"] == 1


async def test_an_unknown_target_field_is_refused_before_any_row_is_written(
    client: httpx.AsyncClient,
) -> None:
    payload = _csv(
        "BRD-1;Fatura üretimi;billing-core;billing;billing;8;10;17;12;timesheet;15.03.2024"
    )

    response = await client.post(
        "/v1/ledger/import",
        files=_files(payload),
        data={"acknowledged": "true", "mapping": '{"kalem": "salary"}'},
    )
    assert response.status_code == 400
    assert "salary" in response.json()["detail"]
    assert (await client.get("/v1/ledger")).json()["total"] == 0


async def test_a_non_spreadsheet_upload_is_refused_by_type(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/ledger/import",
        files={"file": ("payload.exe", b"MZ\x90\x00", "application/octet-stream")},
        data={"acknowledged": "true"},
    )
    assert response.status_code == 415


async def test_an_oversized_upload_is_refused_without_being_read_into_the_ledger(
    client: httpx.AsyncClient,
) -> None:
    """The cap is a memory bound: the file is parsed whole before a row is written."""
    from estimo_api.routers.ledger import MAX_UPLOAD_BYTES

    filler = "BRD-1;Fatura;billing-core;billing;billing;8;10;17;12;timesheet;15.03.2024"
    rows = [filler] * ((MAX_UPLOAD_BYTES // len(filler)) + 64)
    response = await client.post(
        "/v1/ledger/import", files=_files(_csv(*rows)), data={"acknowledged": "true"}
    )
    assert response.status_code == 413
    assert (await client.get("/v1/ledger")).json()["total"] == 0


async def test_an_xlsx_seed_set_imports_through_the_same_path(
    client: httpx.AsyncClient,
) -> None:
    """XLSX is the realistic seed format; the CLI read it and the wizard must too."""
    import io

    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(CSV_HEADER.split(";"))
    sheet.append(
        [
            "BRD-9",
            "Fatura üretimi",
            "billing-core",
            "billing",
            "billing",
            8,
            10,
            17,
            12,
            "timesheet",
            "15.03.2024",
        ]
    )
    buffer = io.BytesIO()
    workbook.save(buffer)

    response = await client.post(
        "/v1/ledger/import",
        files={
            "file": (
                "seed.xlsx",
                buffer.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"acknowledged": "true"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["imported"] == 1
    entry = (await client.get("/v1/ledger")).json()["entries"][0]
    assert entry["item_title"] == "Fatura üretimi"
    assert entry["team"] == "billing"


async def test_a_file_that_is_not_really_a_spreadsheet_is_a_400_not_a_500(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/v1/ledger/import/preview",
        files={"file": ("seed.xlsx", b"not a zip at all", "application/octet-stream")},
    )
    assert response.status_code == 400
    assert "XLSX" in response.json()["detail"]


async def test_importing_the_same_file_twice_does_not_double_the_ledger(
    client: httpx.AsyncClient,
) -> None:
    """A duplicate is one observation counted twice.

    Both readers of this table treat every row as an independent sample: calibration
    grades ranges against them, and retrieval offers them as analogs — so a second
    copy inflates the sample AND becomes its own nearest analog. Re-running an import
    (a retry, a file sent twice, a wizard nobody was sure had worked) must be a no-op
    that says so.
    """
    payload = _csv(
        "BRD-1;Fatura üretimi;billing-core;billing;billing;8;10;17;12;timesheet;15.03.2024"
    )
    first = await client.post(
        "/v1/ledger/import", files=_files(payload), data={"acknowledged": "true"}
    )
    assert first.json()["imported"] == 1

    second = await client.post(
        "/v1/ledger/import", files=_files(payload), data={"acknowledged": "true"}
    )
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["imported"] == 0
    assert [row["row"] for row in body["duplicates"]] == [2]
    assert (await client.get("/v1/ledger")).json()["total"] == 1


async def test_a_row_that_differs_in_its_numbers_is_not_a_duplicate(
    client: httpx.AsyncClient,
) -> None:
    """The dedupe key is the whole observation — a re-estimate of the same item is a
    genuinely new record, and dropping it would be silent data loss."""
    base = "BRD-1;Fatura üretimi;billing-core;billing;billing;8;10;17;12;timesheet;15.03.2024"
    revised = "BRD-1;Fatura üretimi;billing-core;billing;billing;8;10;17;19;timesheet;15.03.2024"
    await client.post("/v1/ledger/import", files=_files(_csv(base)), data={"acknowledged": "true"})
    second = await client.post(
        "/v1/ledger/import", files=_files(_csv(revised)), data={"acknowledged": "true"}
    )
    assert second.json()["imported"] == 1
    assert second.json()["duplicates"] == []
    assert (await client.get("/v1/ledger")).json()["total"] == 2


async def test_two_columns_cannot_be_mapped_to_one_field(client: httpx.AsyncClient) -> None:
    """`_canonicalize` takes whichever non-empty value comes first in the ROW, so a
    colliding mapping makes the imported number depend on column order — and it could
    differ row to row within one file. Refused, not silently resolved."""
    payload = b"brd_ref;kalem;efor;tahmin\nBRD-1;Fatura;10;40"
    response = await client.post(
        "/v1/ledger/import",
        files=_files(payload),
        data={
            "acknowledged": "true",
            "mapping": (
                '{"brd_ref": "brd_ref", "kalem": "item_title",'
                ' "efor": "est_likely", "tahmin": "est_likely"}'
            ),
        },
    )
    assert response.status_code == 400
    assert "est_likely" in response.json()["detail"]
    assert (await client.get("/v1/ledger")).json()["total"] == 0


async def test_a_padded_header_still_shows_the_operator_its_data(
    client: httpx.AsyncClient,
) -> None:
    """The sample is the ONLY row content anyone sees before certifying the privacy
    checklist. `csv.DictReader` keys rows by the header as written, so looking a
    sample up by the stripped header blanks every padded column — and the free-text
    columns are exactly the ones the checklist is about."""
    payload = "brd_ref; kalem ;alan\nBRD-1;Fatura üretimi;billing".encode()

    body = (await client.post("/v1/ledger/import/preview", files=_files(payload))).json()
    samples = {column["header"]: column["sample"] for column in body["columns"]}
    assert samples == {"brd_ref": "BRD-1", "kalem": "Fatura üretimi", "alan": "billing"}


async def test_modules_the_ledger_has_never_seen_are_queued_for_review(
    client: httpx.AsyncClient,
) -> None:
    """LEDGER-SCHEMA.md queues unknown modules instead of rejecting the row. The CLI
    is handed a taxonomy; the panel has no operator to ask, so the deployment's own
    history stands in — and on a FIRST import nothing is unknown, because a review
    queue listing the whole seed set tells nobody anything."""
    known = "BRD-1;Fatura üretimi;billing-core;billing;billing;8;10;17;12;timesheet;15.03.2024"
    first = await client.post(
        "/v1/ledger/import", files=_files(_csv(known)), data={"acknowledged": "true"}
    )
    assert first.json()["unknown_modules"] == {}, "the first import has no history to judge against"

    novel = "BRD-2;Yeni akış;faturalama-x;billing;billing;8;10;17;12;timesheet;15.03.2024"
    second = await client.post(
        "/v1/ledger/import", files=_files(_csv(novel)), data={"acknowledged": "true"}
    )
    assert second.json()["unknown_modules"] == {"faturalama-x": 1}
    assert second.json()["imported"] == 1, "an unknown module is queued, never rejected"


@respx.mock
async def test_a_domain_slice_narrows_a_SEARCH_on_both_retrieval_paths(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """Browse, hybrid search and the lexical fallback are three code paths.

    The slice has to reach all three, or one of them returns out-of-domain rows under
    a `sliced: true` header whose counts describe the slice. The mock is installed
    first (hybrid), then removed (fallback), because a test that only ever sees the
    unreachable-gateway path leaves the primary call site unpinned.
    """
    await _add(session, title="Konsolide fatura kampanya raporu", domains=("charging",))
    billing = await _add(session, title="Konsolide fatura üretimi", domains=("billing",))
    route = respx.post("http://mock-llm.invalid/v1/embeddings").respond(
        json={
            "object": "list",
            "model": "mock-small",
            "data": [{"object": "embedding", "index": 0, "embedding": [1.0, 0.0, 0.0, 0.0]}],
            "usage": {"prompt_tokens": 4, "total_tokens": 4},
        }
    )

    params: dict[str, str | int] = {"q": "fatura kampanya", "domain": "billing", "limit": 5}
    hybrid = (await client.get("/v1/ledger", params=params)).json()
    assert hybrid["retrieval"] == "hybrid", "the dense leg has to have run"
    assert [entry["id"] for entry in hybrid["entries"]] == [str(billing.id)]
    assert hybrid["sliced"] is True
    assert hybrid["total"] == 1

    route.respond(status_code=503)
    fallback = (await client.get("/v1/ledger", params=params)).json()
    assert fallback["retrieval"] == "lexical", "the fallback has to have run"
    assert [entry["id"] for entry in fallback["entries"]] == [str(billing.id)]


@respx.mock
async def test_a_measured_similarity_reaches_the_screen(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """The whole path, with the dense leg actually running.

    Every other similarity test pins an END: the cosine measurement in the retrieval
    package, or "all None" when the dense leg is down. Between them sits the wiring —
    the gateway client, `find_analogs`, the id→score map, `_row` — and dropping the
    similarity argument anywhere along it would leave the chip silently gone with the
    suite still green. respx stands in for the embedding endpoint so the hybrid branch
    is the one under test, not the fallback.
    """
    respx.post("http://mock-llm.invalid/v1/embeddings").respond(
        json={
            "object": "list",
            "model": "mock-small",
            "data": [{"object": "embedding", "index": 0, "embedding": [1.0, 0.0, 0.0, 0.0]}],
            "usage": {"prompt_tokens": 4, "total_tokens": 4},
        }
    )
    near = await _add(session, title="Konsolide fatura üretimi")
    await session.execute(
        update(LedgerEntryRow)
        .where(LedgerEntryRow.id == near.id)
        .values(embedding=[0.6, 0.8, 0.0, 0.0], embedding_model="mock", embedding_dim=4)
    )
    await session.commit()

    body = (await client.get("/v1/ledger", params={"q": "fatura", "limit": 5})).json()
    assert body["retrieval"] == "hybrid"
    entry = next(row for row in body["entries"] if row["id"] == str(near.id))
    # 0.6 is the cosine of the seeded pair — a rank-derived number could not be 0.6.
    assert entry["similarity"] == pytest.approx(0.6, abs=1e-6)


@respx.mock
async def test_a_gateway_that_answers_with_nonsense_degrades_instead_of_500ing(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """The failure surface is the provider SDK, not our gateway wrapper.

    A gateway that returns 200 with a body the SDK cannot parse raises out of the
    SDK's own response parser — not `GatewayError` — and a fallback that catches only
    `GatewayError` turned search into a 500 while browse kept working.
    """
    respx.post("http://mock-llm.invalid/v1/embeddings").respond(json={"unexpected": "shape"})
    await _add(session, title="Konsolide fatura üretimi")

    response = await client.get("/v1/ledger", params={"q": "fatura"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["entries"], "the lexical leg still has to answer"
    assert {entry["similarity"] for entry in body["entries"]} == {None}
    assert body["retrieval"] == "lexical"


async def test_an_oversized_body_is_refused_before_the_route_is_reached(
    client: httpx.AsyncClient,
) -> None:
    """The endpoint's own cap runs AFTER Starlette has parsed the multipart body.

    Route dependencies — including the admin gate — resolve after parsing too, and
    the parser spools past 1 MB to a temp file with no ceiling, so an unauthenticated
    caller could make the server write to disk on the way to a 401. The ceiling has
    to sit in front of the routing table, which is why this test posts to a path that
    does not exist: a 413 rather than a 404 proves nothing downstream ran.
    """
    from estimo_api.main import MAX_REQUEST_BYTES

    oversized = b"x" * (MAX_REQUEST_BYTES + 1024)
    declared = await client.post("/v1/ledger/no-such-route", content=oversized)
    assert declared.status_code == 413, declared.text

    # Content-Length is a claim. A chunked upload declares nothing, so the ceiling
    # also has to count the bytes as they arrive — here against the real import
    # route, because the counter only runs while something is reading the body.
    boundary = "----estimo-oversized"

    async def _chunks() -> AsyncIterator[bytes]:
        yield (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="seed.csv"\r\n'
            "Content-Type: text/csv\r\n\r\n"
        ).encode()
        for _ in range(13):
            yield b"y" * (1024 * 1024)
        yield f"\r\n--{boundary}--\r\n".encode()

    streamed = await client.post(
        "/v1/ledger/import",
        content=_chunks(),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    assert streamed.status_code == 413, streamed.text
