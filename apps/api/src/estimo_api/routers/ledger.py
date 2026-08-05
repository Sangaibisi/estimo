"""Ledger & analog search (design screen 7): read-only views over the estimate ledger,
plus the seed-set import the ledger starts from.

The screen's whole argument is the outside view — what similar past work actually
cost — so every row carries the estimate given, the actual, and the deviation, and
search runs through the same Turkish hybrid retrieval the estimator uses.
"""

from __future__ import annotations

import json
import logging
import uuid
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Any

from estimo_knowledge import (
    ImportReport,
    LedgerEntryRow,
    find_analogs,
    import_rows,
    propose_mapping,
    read_rows,
)
from estimo_knowledge.importer import COLUMN_ALIASES
from estimo_knowledge.search import ledger_slice_conditions
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimo_api.auth import require_admin
from estimo_api.db import get_session
from estimo_api.runtime_config import effective_gateway, gateway_client

logger = logging.getLogger("estimo.api.ledger")

router = APIRouter(prefix="/v1/ledger", tags=["ledger"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# An upload is parsed entirely in memory before a single row is written, so the cap is
# a memory bound, not a policy. A seed set of tens of thousands of rows fits well inside.
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
# XLSX is a zip: a few kilobytes on the wire can expand into gigabytes of XML. openpyxl
# streams in read-only mode but still expands each sheet part, so the declared expansion
# is checked BEFORE the file is opened.
MAX_XLSX_EXPANDED_BYTES = 256 * 1024 * 1024
ALLOWED_SUFFIXES = (".csv", ".xlsx", ".xlsm")
# One short value per column, so the privacy checklist is answerable — an operator
# cannot certify "no personal data in free-text fields" against column names alone.
SAMPLE_CHARS = 60
# Facet values carried per response. `domain` is free text on the import path, so its
# cardinality is bounded by the data, not the schema.
MAX_FACET_VALUES = 200

ESTIMATE_ORIGIN_PREFIX = "estimate://"


def _boe_link(origin_ref: str | None) -> dict[str, str] | None:
    """`estimate://{estimate_id}/{work_item_id}` → the row it came from.

    Product-written entries are the only ones that HAVE a source row; imported seed
    rows predate the product and link nowhere, which is why this returns None rather
    than a link that 404s.
    """
    if not origin_ref or not origin_ref.startswith(ESTIMATE_ORIGIN_PREFIX):
        return None
    rest = origin_ref[len(ESTIMATE_ORIGIN_PREFIX) :]
    estimate_id, _, work_item_id = rest.partition("/")
    if not estimate_id or not work_item_id:
        return None
    try:
        uuid.UUID(estimate_id)
    except ValueError:
        return None
    return {"estimate_id": estimate_id, "work_item_id": work_item_id}


def _row(row: LedgerEntryRow, similarity: float | None = None) -> dict[str, Any]:
    likely = float(row.est_likely) if row.est_likely is not None else None
    single = float(row.estimate_single) if row.estimate_single is not None else None
    estimate = likely if likely is not None else single
    actual = float(row.actual_effort) if row.actual_effort is not None else None
    return {
        "id": str(row.id),
        "brd_ref": row.brd_ref,
        "item_title": row.item_title,
        "module_tags": list(row.module_tags or ()),
        "domain_tags": list(row.domain_tags or ()),
        "team": row.team,
        "discipline": row.discipline,
        "estimate": (
            {
                "optimistic": float(row.est_optimistic) if row.est_optimistic is not None else None,
                "likely": likely,
                "pessimistic": (
                    float(row.est_pessimistic) if row.est_pessimistic is not None else None
                ),
                "single": single,
            }
        ),
        "actual_effort": actual,
        "actual_source": row.actual_source,
        "scope_changed": row.scope_changed,
        "deviation": round(actual / estimate, 2) if actual is not None and estimate else None,
        "origin": "product" if row.origin_ref else "imported",
        "boe_link": _boe_link(row.origin_ref),
        "estimated_at": row.estimated_at.isoformat() if row.estimated_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        # Present only when the dense leg actually measured it (estimo_knowledge.search).
        "similarity": similarity,
    }


async def _facets(session: AsyncSession) -> dict[str, Any]:
    """The teams and domains that exist, for the slice chips.

    Read from the ledger itself rather than a configured list: a chip that filters to
    nothing is worse than a missing chip.

    BOUNDED. Nothing on the import path constrains domain cardinality — `domain` is
    free text, lowercased and stored — so a messy seed set can hold thousands of
    distinct values, and an unbounded facet list would ride along on every single
    ledger response. Past the cap the lists are truncated and the response says so,
    instead of a filter control quietly becoming a several-hundred-kilobyte payload.
    """
    teams = (
        await session.execute(
            select(LedgerEntryRow.team)
            .where(LedgerEntryRow.team.is_not(None))
            .distinct()
            .order_by(LedgerEntryRow.team)
            .limit(MAX_FACET_VALUES + 1)
        )
    ).scalars()
    domain_rows = (
        await session.execute(
            select(func.unnest(LedgerEntryRow.domain_tags).label("domain"))
            .distinct()
            .limit(MAX_FACET_VALUES + 1)
        )
    ).scalars()
    discipline_rows = (
        await session.execute(
            select(LedgerEntryRow.discipline)
            .where(LedgerEntryRow.discipline.is_not(None))
            .distinct()
            .order_by(LedgerEntryRow.discipline)
        )
    ).scalars()
    team_list = [team for team in teams if team]
    domain_list = sorted({domain for domain in domain_rows if domain})
    return {
        "teams": team_list[:MAX_FACET_VALUES],
        "domains": domain_list[:MAX_FACET_VALUES],
        # At most two values by construction (the import boundary rejects anything
        # else), so no cap is needed.
        "disciplines": [d for d in discipline_rows if d],
        "truncated": len(team_list) > MAX_FACET_VALUES or len(domain_list) > MAX_FACET_VALUES,
    }


async def _known_modules(session: AsyncSession) -> set[str] | None:
    """Module tags the ledger has seen before — the import's review-queue taxonomy.

    LEDGER-SCHEMA.md wants unknown modules queued for review rather than rejected. The
    CLI takes the taxonomy as an argument; the panel has no operator to ask, so the
    deployment's own history stands in: a module that has never appeared in the ledger
    is what an operator needs to look at (a typo, or genuinely new work). Returns None
    for an empty ledger — on a first import EVERY module is new, and a review queue
    listing the entire seed set tells nobody anything.
    """
    result = await session.execute(
        select(func.unnest(LedgerEntryRow.module_tags).label("module")).distinct()
    )
    known = {module for module in result.scalars() if module}
    return known or None


@router.get("")
async def list_ledger(
    session: SessionDep,
    request: Request,
    q: Annotated[str, Query(max_length=200)] = "",
    team: Annotated[str, Query(max_length=80)] = "",
    domain: Annotated[str, Query(max_length=60)] = "",
    discipline: Annotated[str, Query(max_length=20)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    """Browse the ledger, or search it through the analog retrieval path.

    An empty query lists the newest entries; a query returns the ranked analog set
    the estimator would see, so the screen and the estimator agree by construction.
    The team/domain slice is pushed INTO retrieval (not applied to its output), so a
    sliced search still returns the best matches within the slice.
    """
    slice_conditions = ledger_slice_conditions(team or None, domain or None, discipline or None)
    summary = (
        await session.execute(
            select(
                func.count(LedgerEntryRow.id),
                func.count(LedgerEntryRow.actual_effort),
            ).where(*slice_conditions)
        )
    ).one()

    retrieval = "lexical"
    if q.strip():
        # The panel-configured gateway, when there is one: without it retrieval is
        # lexical-only and every similarity comes back None rather than invented.
        client = gateway_client(await effective_gateway(request, session))
        try:
            cards = await find_analogs(
                session,
                q,
                client=client,
                limit=limit,
                team=team or None,
                domain=domain or None,
                discipline=discipline or None,
            )
            retrieval = "hybrid" if client is not None else "lexical"
        except Exception:
            # An unreachable embedding endpoint must not take the ledger down: the
            # lexical leg alone still answers the question this screen asks. The
            # answer is narrower, so the caller is TOLD it is narrower rather than
            # being handed a degraded list that looks like the full one.
            #
            # Broad on purpose. GatewayError covers what OUR gateway package raises,
            # but the failure surface is the provider SDK underneath it: a gateway
            # that answers /embeddings with 200 and a body the SDK cannot parse
            # raises ValueError/AttributeError/binascii.Error from inside the SDK's
            # own response parser, and those turned a search into a 500 while browse
            # kept working. The fallback below is a plain SQL query that cannot
            # depend on any of it, so degrading is always safe here; the exception is
            # logged with its traceback rather than swallowed.
            logger.warning("ledger search fell back to the lexical leg", exc_info=True)
            cards = await find_analogs(
                session,
                q,
                limit=limit,
                team=team or None,
                domain=domain or None,
                discipline=discipline or None,
            )
        similarity = {card.entry_id: card.similarity for card in cards}
        ids = [card.entry_id for card in cards]
        rows = {
            row.id: row
            for row in (
                await session.execute(select(LedgerEntryRow).where(LedgerEntryRow.id.in_(ids)))
            ).scalars()
        }
        entries = [_row(rows[i], similarity.get(i)) for i in ids if i in rows]
    else:
        result = await session.execute(
            select(LedgerEntryRow)
            .where(*slice_conditions)
            .order_by(LedgerEntryRow.created_at.desc())
            .limit(limit)
        )
        entries = [_row(row) for row in result.scalars()]

    return {
        "entries": entries,
        "total": int(summary[0] or 0),
        "with_actuals": int(summary[1] or 0),
        "searched": bool(q.strip()),
        "sliced": bool(slice_conditions),
        # "hybrid" only when the dense leg actually ran. A screen that shows no
        # similarity percentages should be able to say WHY.
        "retrieval": retrieval,
        "facets": await _facets(session),
    }


async def _upload_bytes(upload: UploadFile) -> bytes:
    """Read the upload under a hard cap, without trusting Content-Length."""
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail=f"unsupported file type {suffix or '(none)'}; expected CSV or XLSX",
        )
    chunks: list[bytes] = []
    size = 0
    while chunk := await upload.read(64 * 1024):
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"file exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
            )
        chunks.append(chunk)
    if not chunks:
        raise HTTPException(status_code=400, detail="file is empty")
    return b"".join(chunks)


def _parse_upload(name: str, payload: bytes) -> list[dict[str, str]]:
    suffix = Path(name).suffix.lower()
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / f"upload{suffix}"
        path.write_bytes(payload)
        if suffix in (".xlsx", ".xlsm"):
            try:
                with zipfile.ZipFile(path) as archive:
                    expanded = sum(info.file_size for info in archive.infolist())
            except zipfile.BadZipFile as exc:
                raise HTTPException(status_code=400, detail="not a readable XLSX file") from exc
            if expanded > MAX_XLSX_EXPANDED_BYTES:
                raise HTTPException(
                    status_code=413, detail="XLSX expands to more than the parser will read"
                )
        try:
            return read_rows(path)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"could not read the file: {type(exc).__name__}"
            ) from exc


def _clip(value: str) -> str:
    text = value.strip()
    return text if len(text) <= SAMPLE_CHARS else text[: SAMPLE_CHARS - 1] + "…"


@router.post("/import/preview", dependencies=[Depends(require_admin)])
async def preview_import(file: Annotated[UploadFile, File()]) -> dict[str, Any]:
    """Step 1→2 of the wizard: what is in this file, and where would each column go?

    Nothing is written — the operator confirms the mapping and the privacy checklist
    before any row exists.
    """
    payload = await _upload_bytes(file)
    rows = _parse_upload(file.filename or "upload.csv", payload)
    if not rows:
        raise HTTPException(status_code=400, detail="file has a header but no rows")
    # The header as WRITTEN is the dict key (csv.DictReader keeps "brd_ref; kalem "
    # padding verbatim); the stripped form is what the operator sees and maps. Sample
    # values must be looked up by the raw key or every padded column previews blank —
    # and the blank columns would be exactly the free-text ones the privacy checklist
    # exists to check, so the operator would certify against column names alone.
    raw_headers = [str(header or "") for header in rows[0]]
    proposal = propose_mapping([header.strip() for header in raw_headers])
    columns = [
        {
            "header": header.strip(),
            "field": proposal.get(header.strip()),
            "sample": next(
                (
                    _clip(str(row.get(header) or ""))
                    for row in rows
                    if str(row.get(header) or "").strip()
                ),
                "",
            ),
        }
        for header in raw_headers
        if header.strip()
    ]
    mapped = {column["field"] for column in columns if column["field"]}
    return {
        "source": file.filename,
        "rows": len(rows),
        "columns": columns,
        "fields": sorted(COLUMN_ALIASES),
        # Told plainly rather than discovered row-by-row after the import ran.
        "missing_required": [name for name in ("brd_ref", "item_title") if name not in mapped],
    }


def _report_payload(report: ImportReport) -> dict[str, Any]:
    return {
        "source": report.source,
        "total_rows": report.total_rows,
        "imported": report.imported,
        "without_actuals": report.without_actuals,
        "duplicates": report.duplicates,
        "rejected": report.rejected,
        "warnings": report.warnings,
        "unknown_modules": report.unknown_modules,
    }


@router.post("/import", dependencies=[Depends(require_admin)])
async def run_import(
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    mapping: Annotated[str, Form()] = "",
    acknowledged: Annotated[bool, Form()] = False,
) -> dict[str, Any]:
    """Step 3→4: import the file under a confirmed column mapping.

    `acknowledged` is the privacy checklist, and it is enforced HERE rather than in
    the browser: the checklist is the only moment anyone asserts that a file about to
    become permanent vendor memory carries no personal data (SECURITY.md), and a
    client-side-only gate is not an assertion, it is a decoration.
    """
    if not acknowledged:
        raise HTTPException(
            status_code=400,
            detail="the privacy checklist must be confirmed before any row is imported",
        )
    payload = await _upload_bytes(file)
    rows = _parse_upload(file.filename or "upload.csv", payload)
    if not rows:
        raise HTTPException(status_code=400, detail="file has a header but no rows")

    confirmed: dict[str, str] | None = None
    if mapping.strip():
        try:
            parsed = json.loads(mapping)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="mapping is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="mapping must be an object")
        unknown = {
            str(value) for value in parsed.values() if value and str(value) not in COLUMN_ALIASES
        }
        if unknown:
            raise HTTPException(
                status_code=400, detail=f"unknown target fields: {', '.join(sorted(unknown))}"
            )
        confirmed = {str(header).strip(): str(value) for header, value in parsed.items() if value}
        # Two columns feeding one field is not a preference the server can resolve:
        # `_canonicalize` takes whichever non-empty value comes first in the ROW, so
        # the imported number would depend on column order and could differ row to
        # row within one file. propose_mapping never proposes it; a client that posts
        # it back is told, not silently obeyed.
        collisions = sorted(
            {field for field in confirmed.values() if list(confirmed.values()).count(field) > 1}
        )
        if collisions:
            raise HTTPException(
                status_code=400,
                detail=f"more than one column maps to: {', '.join(collisions)}",
            )

    report = await import_rows(
        session,
        rows,
        source=file.filename or "upload",
        taxonomy=await _known_modules(session),
        mapping=confirmed,
    )
    return _report_payload(report)
