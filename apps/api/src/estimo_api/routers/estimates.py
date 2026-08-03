"""Estimate workflow endpoints (S7 backend).

Independent-first is SERVER-enforced (PRINCIPLES #4) across the whole surface, not
just the desk: AI bands are reachable only via the desk (per-estimator, after their
own band exists) until every line of the current draft is signed — GET, the build
response and the .docx export all withhold band content before full sign-off, and a
signature itself requires the signer's revealed independent band. Anchors stay
visible here (humans see them); only model boundaries redact.

Identity: with OIDC configured the estimator/signer is taken from the validated
token (`_bound_identity`), so the anchoring telemetry and the signature trail cannot
be forged by a client-supplied name. In single-tenant (auth-disabled) mode the caller
names themselves, which is the historical behaviour.

The reveal — and the anchoring delta it measures — is emitted by POST /independent,
the act that earns it, NOT by GET /desk. The desk is a pure read. Emitting it from a
read meant a link prefetch, a crawler retry, or anyone passing a colleague's name in
the query string could flip that colleague's row (bands are immutable, so
irreversibly) and write an anchoring sample for a reveal that never happened to a
person who never saw it.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import re
import statistics
import tempfile
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote

from estimo_estimate import estimate_state, record_actual, render_boe_docx, review_boe
from estimo_estimate.loop import origin_ref as make_origin_ref
from estimo_knowledge import LedgerEntryRow
from estimo_pipeline import PipelineState, resume_with_answers, run_brd
from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from estimo_api import telemetry
from estimo_api.auth import Principal, current_principal, require_signing
from estimo_api.db import get_session
from estimo_api.estimates_models import (
    EstimateRecord,
    IndependentEstimate,
    LineSignature,
    UiEvent,
)
from estimo_core import BoeDocument, Signature

router = APIRouter(prefix="/v1/estimates", tags=["estimates"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024

# Kinds the server writes with integrity semantics; clients may not forge them.
RESERVED_EVENT_KINDS = frozenset({"independent-recorded", "draft-revealed", "actual-recorded"})


class EstimateSummary(BaseModel):
    id: uuid.UUID
    brd_ref: str
    title: str
    status: str
    requirements: int
    blocked: int
    open_questions: int
    work_items: int
    has_boe: bool


def _summary(record: EstimateRecord) -> EstimateSummary:
    state = PipelineState.model_validate(record.state)
    answered = set(state.answers)
    return EstimateSummary(
        id=record.id,
        brd_ref=record.brd_ref,
        title=record.title,
        status=record.status,
        requirements=len(state.requirements),
        blocked=len(state.blocked_ids),
        open_questions=sum(1 for q in state.questions if q.id not in answered),
        work_items=len(state.work_items),
        has_boe=record.boe is not None,
    )


async def _get_record(session: AsyncSession, estimate_id: uuid.UUID) -> EstimateRecord:
    record = await session.get(EstimateRecord, estimate_id)
    if record is None:
        raise HTTPException(status_code=404, detail="estimate not found")
    return record


async def _signed_item_ids(session: AsyncSession, record: EstimateRecord) -> set[str]:
    """Work items signed against the CURRENT draft version only."""
    rows = await session.execute(
        select(LineSignature.work_item_id).where(
            LineSignature.estimate_id == record.id,
            LineSignature.boe_version == record.boe_version,
        )
    )
    return set(rows.scalars())


async def _fully_signed(session: AsyncSession, record: EstimateRecord) -> bool:
    if record.boe is None:
        return False
    boe = BoeDocument.model_validate(record.boe)
    line_ids = {line.work_item_id for line in boe.lines}
    return bool(line_ids) and line_ids <= await _signed_item_ids(session, record)


def _bound_identity(request: Request, principal: Principal, claimed: str) -> str:
    """The estimator/signer identity of record.

    With OIDC configured the identity comes from the validated token — a
    client-supplied name would make the independent-first telemetry and the
    signature trail forgeable. In single-tenant (auth-disabled) mode the caller
    names themselves, which is the historical behaviour.
    """
    if getattr(request.app.state, "oidc_verifier", None) is None:
        return claimed
    return principal.subject


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_estimate(file: UploadFile, session: SessionDep) -> EstimateSummary:
    if not (file.filename or "").lower().endswith(".docx"):
        raise HTTPException(status_code=422, detail="a .docx BRD is required")
    # Enforce the size limit while streaming — an unsized read() would materialise a
    # multi-GB body in memory before the 413 is ever raised.
    chunks: list[bytes] = []
    received = 0
    while chunk := await file.read(UPLOAD_CHUNK_BYTES):
        received += len(chunk)
        if received > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="BRD exceeds the 20 MB limit")
        chunks.append(chunk)
    payload = b"".join(chunks)
    with tempfile.TemporaryDirectory() as tmp:
        brd_path = Path(tmp) / (Path(file.filename or "brd.docx").name)
        brd_path.write_bytes(payload)
        try:
            state = await run_brd(brd_path, thread_id=f"api-{uuid.uuid4()}")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    brd_ref = state.parsed.brd_ref if state.parsed else brd_path.stem
    title = state.parsed.title if state.parsed else brd_path.stem
    record = EstimateRecord(
        # Document-controlled text; clip to the column widths instead of 500ing
        # after the whole pipeline already ran.
        brd_ref=brd_ref[:120],
        title=title[:300],
        status=state.status,
        state=state.model_dump(mode="json"),
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return _summary(record)


@router.get("")
async def list_estimates(
    session: SessionDep, limit: Annotated[int, Query(ge=1, le=100)] = 50
) -> list[EstimateSummary]:
    result = await session.execute(
        select(EstimateRecord).order_by(EstimateRecord.created_at.desc()).limit(limit)
    )
    return [_summary(record) for record in result.scalars()]


@router.get("/{estimate_id}")
async def get_estimate(estimate_id: uuid.UUID, session: SessionDep) -> dict[str, Any]:
    record = await _get_record(session, estimate_id)
    fully_signed = await _fully_signed(session, record)
    return {
        "summary": _summary(record).model_dump(mode="json"),
        "state": record.state,
        # Independent-first: the draft body (every line's band) leaves the desk's
        # per-estimator gate only after the whole draft is signed off.
        "boe": record.boe if fully_signed else None,
        "critic": record.critic or [],
        "fully_signed": fully_signed,
    }


class AnswersIn(BaseModel):
    answers: dict[str, str]


@router.post("/{estimate_id}/answers")
async def apply_answers(
    estimate_id: uuid.UUID, payload: AnswersIn, session: SessionDep
) -> EstimateSummary:
    # An empty answer is "no answer" — merging it would silently close the question.
    answers = {key: value for key, value in payload.answers.items() if value.strip()}
    if not answers:
        raise HTTPException(status_code=422, detail="no non-empty answers submitted")
    record = await _get_record(session, estimate_id)
    state = PipelineState.model_validate(record.state)
    try:
        state = await resume_with_answers(state, answers)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record.state = state.model_dump(mode="json")
    record.status = state.status
    record.boe = None  # answers invalidate any previous draft
    record.critic = None
    await session.commit()
    await session.refresh(record)
    return _summary(record)


@router.post("/{estimate_id}/estimate")
async def build_boe(estimate_id: uuid.UUID, session: SessionDep) -> dict[str, Any]:
    record = await _get_record(session, estimate_id)
    if record.boe is not None:
        raise HTTPException(
            status_code=409,
            detail="a draft already exists; apply answers to invalidate it before rebuilding",
        )
    state = PipelineState.model_validate(record.state)
    try:
        boe = await estimate_state(session, state)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    findings = review_boe(boe, state)
    # Computed fields (total) serialize but are rejected on re-validation
    # (extra="forbid") — persist the storable projection only.
    record.boe = boe.model_dump(mode="json", exclude={"total"})
    record.boe_version += 1
    record.critic = findings
    record.status = "boe_draft"
    await session.commit()
    # No draft body here (independent-first): bands are reachable only through the
    # per-estimator desk gate until full sign-off.
    return {"status": "boe_draft", "version": record.boe_version, "critic": findings}


class IndependentIn(BaseModel):
    work_item_id: str
    estimator: str = Field(min_length=1, max_length=120)
    optimistic: float = Field(ge=0)
    likely: float = Field(ge=0)
    pessimistic: float = Field(ge=0)
    # Optional, and only capturable HERE: after the draft is revealed any rationale
    # is a rationalization of the delta, not the reasoning that produced the band.
    rationale: str | None = Field(default=None, max_length=2000)


@router.post("/{estimate_id}/independent", status_code=status.HTTP_201_CREATED)
async def record_independent(
    estimate_id: uuid.UUID,
    payload: IndependentIn,
    session: SessionDep,
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
) -> dict[str, str]:
    estimator = _bound_identity(request, principal, payload.estimator)
    if not payload.optimistic <= payload.likely <= payload.pessimistic:
        raise HTTPException(status_code=422, detail="band must be ordered o <= l <= p")
    record = await _get_record(session, estimate_id)
    if record.boe is None:
        # Bands are stamped with the draft version they compare against.
        raise HTTPException(status_code=409, detail="build the BoE draft first")
    state = PipelineState.model_validate(record.state)
    if payload.work_item_id not in {item.id for item in state.work_items}:
        raise HTTPException(status_code=404, detail="work item not found")
    existing = await session.scalar(
        select(IndependentEstimate).where(
            IndependentEstimate.estimate_id == estimate_id,
            IndependentEstimate.work_item_id == payload.work_item_id,
            IndependentEstimate.estimator == estimator,
            IndependentEstimate.boe_version == record.boe_version,
        )
    )
    if existing is not None:
        # Immutable by design: revising the independent value after seeing the draft
        # would defeat the anchoring telemetry.
        raise HTTPException(status_code=409, detail="independent estimate already recorded")
    # Recording IS the reveal. The anchoring measurement belongs to this moment — the
    # estimator has irrevocably committed a number (bands are immutable), so the AI
    # band unlocks for them here. It used to be emitted from GET /desk, which made a
    # read mutate state: a link prefetch, a crawler, or anyone passing a colleague's
    # name in the query string could flip that colleague's un-revealed row forever and
    # fabricate the anchoring delta PRINCIPLES #4 exists to measure honestly.
    boe = BoeDocument.model_validate(record.boe)
    line = next((ln for ln in boe.lines if ln.work_item_id == payload.work_item_id), None)
    delta_likely = round(float(payload.likely) - line.range.likely, 1) if line is not None else None
    session.add(
        IndependentEstimate(
            estimate_id=estimate_id,
            work_item_id=payload.work_item_id,
            estimator=estimator,
            boe_version=record.boe_version,
            optimistic=payload.optimistic,
            likely=payload.likely,
            pessimistic=payload.pessimistic,
            rationale=(payload.rationale or "").strip() or None,
            revealed=line is not None,
        )
    )
    session.add(
        UiEvent(
            estimate_id=estimate_id,
            kind="independent-recorded",
            payload={"work_item_id": payload.work_item_id, "estimator": estimator},
        )
    )
    if delta_likely is not None:
        session.add(
            UiEvent(
                estimate_id=estimate_id,
                kind="draft-revealed",
                payload={
                    "work_item_id": payload.work_item_id,
                    "estimator": estimator,
                    "delta_likely": delta_likely,
                    "boe_version": record.boe_version,
                },
            )
        )
    try:
        await session.commit()
    except IntegrityError as exc:
        # Concurrent duplicate lost the check-then-insert race; same contract as the
        # sequential path.
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="independent estimate already recorded"
        ) from exc
    telemetry.emit_event(
        "independent-recorded", str(estimate_id), {"work_item_id": payload.work_item_id}
    )
    if delta_likely is not None:
        telemetry.emit_score("anchoring-delta-likely", float(delta_likely), str(estimate_id))
    return {"status": "recorded"}


# A Delphi panel opens only once three estimators have recorded on the SAME item.
# k=1 is self-disclosure; k=2 de-anonymizes completely, because the you-first gate makes
# every viewer a participant — you see two lines, one is yours, so the other is the only
# other panelist's. k=3 leaves every viewer a 2-anonymity set over the lines that are not
# theirs. The delivered design labels the overlay "3 reviewers, anonymous".
DELPHI_MIN_ESTIMATORS = 3


def _delphi_block(rows: list[IndependentEstimate], has_own: bool) -> dict[str, Any]:
    """Anonymized panel view for ONE work item.

    Two gates, in precedence order. `you_first`: the requester has not recorded their
    own band for this item, so showing them anyone else's would be the anchoring leak
    the whole desk exists to prevent (PRINCIPLES #4). `below_threshold`: fewer than
    three estimators, so any band-shaped number identifies a person.

    Below either gate the block carries NO band-shaped value at all — not a median, not
    a min, not a max. With two panelists a median plus your own band reconstructs the
    other person's exactly, so a "summary only" concession would leak the same data
    with extra steps. Only the participation count survives, because a count is not a
    numeric anchor and it is what makes the closed state honest.
    """
    closed: dict[str, Any] = {
        "estimators": len(rows),
        "threshold": DELPHI_MIN_ESTIMATORS,
        "bands": [],
        "consensus": None,
        "spread_likely": None,
        "overlap": None,
    }
    if not has_own:
        return {"state": "you_first", **closed}
    if len(rows) < DELPHI_MIN_ESTIMATORS:
        return {"state": "below_threshold", **closed}

    # Sorted by VALUE, never by created_at or estimator name. Recording order is
    # observable elsewhere on the desk, so an order-preserving list would map lines
    # back to people. Re-sorted per item, so no line index is stable across rows —
    # which is also why there are no "Reviewer A/B/C" pseudonyms.
    bands = sorted(
        (
            {
                "optimistic": float(row.optimistic),
                "likely": float(row.likely),
                "pessimistic": float(row.pessimistic),
            }
            for row in rows
        ),
        key=lambda band: (band["optimistic"], band["likely"], band["pessimistic"]),
    )
    likelies = [band["likely"] for band in bands]
    return {
        "state": "open",
        "estimators": len(rows),
        "threshold": DELPHI_MIN_ESTIMATORS,
        "bands": bands,
        # Per-endpoint median: the consensus stays a RANGE (PRINCIPLES #1 — never a
        # point), and one outlier band cannot drag it the way a mean would.
        "consensus": {
            key: round(statistics.median(band[key] for band in bands), 1)
            for key in ("optimistic", "likely", "pessimistic")
        },
        # The design's headline: the width of the disagreement is the finding.
        "spread_likely": round(max(likelies) - min(likelies), 1),
        "overlap": (
            "intersect"
            if max(band["optimistic"] for band in bands)
            <= min(band["pessimistic"] for band in bands)
            else "disjoint"
        ),
    }


@router.get("/{estimate_id}/desk")
async def estimate_desk(
    estimate_id: uuid.UUID,
    session: SessionDep,
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
    estimator: Annotated[str, Query(min_length=1)],
) -> dict[str, Any]:
    """Independent-first desk: AI bands appear per item ONLY after the estimator's own
    band exists for that item against the CURRENT draft (server-enforced, PRINCIPLES #4).

    The gate covers every DRAFT-DERIVED field, not just the band. The design draws a
    confidence grade and a discovery chip in the closed state, and both were shipped
    that way for one review cycle — until an audit showed the estimator's own pipeline
    makes them invertible: the no-analog branch pins the band at 1/3/8 pd, confidence
    at LOW and the contingency at 4.0 pd together, so "low" or "4 pd" on a closed row
    IS the band, and the analog branch derives the contingency as 30% of likely, which
    divides straight back out. A grade is only safe to show when it is not a proxy for
    a number; here it is one, so it waits for the reveal like everything else. Closing
    the gap for real means decoupling the grade from the band in the estimator
    (ROADMAP S12-1), not loosening this endpoint."""
    estimator = _bound_identity(request, principal, estimator)
    record = await _get_record(session, estimate_id)
    state = PipelineState.model_validate(record.state)
    boe = BoeDocument.model_validate(record.boe) if record.boe else None
    lines_by_item = {line.work_item_id: line for line in (boe.lines if boe else ())}

    # Every estimator's rows for this draft: the requester's drive independent-first,
    # the rest form the Delphi panel. Scoped to boe_version like every other read here,
    # so a rebuilt draft inherits no one's band.
    panel: dict[str, list[IndependentEstimate]] = defaultdict(list)
    independents: dict[str, IndependentEstimate] = {}
    for row in (
        await session.execute(
            select(IndependentEstimate).where(
                IndependentEstimate.estimate_id == estimate_id,
                IndependentEstimate.boe_version == record.boe_version,
            )
        )
    ).scalars():
        panel[row.work_item_id].append(row)
        if row.estimator == estimator:
            independents[row.work_item_id] = row
    signatures = await _signed_item_ids(session, record)

    items: list[dict[str, Any]] = []
    for item in state.work_items:
        independent = independents.get(item.id)
        line = lines_by_item.get(item.id)
        entry: dict[str, Any] = {
            "work_item": item.model_dump(mode="json"),
            "independent": (
                {
                    "optimistic": float(independent.optimistic),
                    "likely": float(independent.likely),
                    "pessimistic": float(independent.pessimistic),
                }
                if independent
                else None
            ),
            "rationale": independent.rationale if independent else None,
            "signed": line is not None and item.id in signatures,
            # Recomputed per item: a panel counted per ESTIMATE would open an item that
            # only two people actually estimated.
            "delphi": _delphi_block(panel[item.id], has_own=independent is not None),
            # NOTHING draft-derived travels before the reveal — see the note below.
            "confidence": None,
            "discovery_pd": None,
            "ai": None,
            "delta_likely": None,
        }
        if independent is not None and line is not None:
            entry["ai"] = line.model_dump(mode="json")
            entry["confidence"] = line.confidence.value
            entry["discovery_pd"] = (
                round(sum(risk.contingency_pd or 0 for risk in line.risks), 1) or None
            )
            entry["delta_likely"] = round(float(independent.likely) - line.range.likely, 1)
        items.append(entry)

    # Blocked requirements are drawn on the desk as HELD rows. Leaving them off made
    # the desk look complete while a requirement sat unpriced behind an open question:
    # "no line item without evidence" is a promise the desk has to show, not hide.
    work_item_requirements = {req for item in state.work_items for req in item.requirement_ids}
    held = [
        {
            "requirement_id": requirement.id,
            "text": requirement.text,
            "reason": (requirement.ambiguity_issues or ["blocked"])[0],
        }
        for requirement in state.requirements
        if requirement.id in set(state.blocked_ids) and requirement.id not in work_item_requirements
    ]
    return {
        "items": items,
        "has_boe": boe is not None,
        "held": held,
        # Cone-of-uncertainty stage the draft was issued at (PRINCIPLES #1). The desk
        # footer shows it because a ±4x concept-stage band is a different promise from
        # a ±1.25x detailed one, and the reader must be told which they are looking at.
        "cone_stage": boe.cone_stage.value if boe else None,
    }


class SignIn(BaseModel):
    work_item_id: str
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=80)


@router.post(
    "/{estimate_id}/sign",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_signing)],
)
async def sign_line(
    estimate_id: uuid.UUID,
    payload: SignIn,
    session: SessionDep,
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
) -> dict[str, str]:
    signer = _bound_identity(request, principal, payload.name)
    record = await _get_record(session, estimate_id)
    if record.boe is None:
        raise HTTPException(status_code=409, detail="no BoE draft to sign")
    boe = BoeDocument.model_validate(record.boe)
    if payload.work_item_id not in {line.work_item_id for line in boe.lines}:
        raise HTTPException(status_code=404, detail="estimate line not found")
    # A signature asserts the signer reviewed the line, which requires having gone
    # through independent-first for it on the current draft.
    reviewed = await session.scalar(
        select(IndependentEstimate).where(
            IndependentEstimate.estimate_id == estimate_id,
            IndependentEstimate.work_item_id == payload.work_item_id,
            IndependentEstimate.estimator == signer,
            IndependentEstimate.boe_version == record.boe_version,
        )
    )
    if reviewed is None:
        raise HTTPException(
            status_code=409, detail="record your independent band for this line before signing"
        )
    session.add(
        LineSignature(
            estimate_id=estimate_id,
            work_item_id=payload.work_item_id,
            boe_version=record.boe_version,
            name=signer,
            role=payload.role,
        )
    )
    await session.commit()
    return {"status": "signed"}


@router.get("/{estimate_id}/boe.docx")
async def download_boe(estimate_id: uuid.UUID, session: SessionDep) -> StreamingResponse:
    record = await _get_record(session, estimate_id)
    if record.boe is None:
        raise HTTPException(status_code=404, detail="no BoE draft")
    if not await _fully_signed(session, record):
        raise HTTPException(
            status_code=409,
            detail="the export contains every band — sign all lines to unlock it",
        )
    boe = BoeDocument.model_validate(record.boe)
    # The signature trail lives in line_signatures, not in the stored BoE JSON — merge
    # it in at export so the artefact that leaves the system names its signers
    # (PRINCIPLES #9). Without this the document's signature table ships blank.
    signature_rows = (
        await session.execute(
            select(LineSignature)
            .where(
                LineSignature.estimate_id == estimate_id,
                LineSignature.boe_version == record.boe_version,
            )
            .order_by(LineSignature.signed_at)
        )
    ).scalars()
    boe = boe.model_copy(
        update={
            "signatures": tuple(
                Signature(
                    name=row.name,
                    role=row.role,
                    scope=row.work_item_id,
                    signed_at=row.signed_at,
                )
                for row in signature_rows
            )
        }
    )
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "boe.docx"
        render_boe_docx(boe, out)
        content = out.read_bytes()
    # brd_ref is document-controlled: ASCII-slug the plain filename (a raw Turkish /
    # quoted value would 500 or allow header injection) and carry the real name in
    # the RFC 5987 filename* parameter, percent-encoded.
    safe_ref = re.sub(r"[^A-Za-z0-9._-]+", "_", record.brd_ref).strip("._-")[:80] or "estimate"
    utf8_ref = quote(f"{record.brd_ref}-boe.docx", safe="")
    return StreamingResponse(
        io.BytesIO(content),
        media_type=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{safe_ref}-boe.docx\"; filename*=UTF-8''{utf8_ref}"
            )
        },
    )


class EventIn(BaseModel):
    kind: str = Field(min_length=1, max_length=60)
    payload: dict[str, Any] | None = None

    @field_validator("payload")
    @classmethod
    def _payload_bounded(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None and len(json.dumps(value)) > 4096:
            raise ValueError("event payload exceeds 4 KB")
        return value


@router.post("/{estimate_id}/events", status_code=status.HTTP_201_CREATED)
async def record_event(
    estimate_id: uuid.UUID, payload: EventIn, session: SessionDep
) -> dict[str, str]:
    if payload.kind in RESERVED_EVENT_KINDS:
        raise HTTPException(
            status_code=422, detail=f"'{payload.kind}' is a server-reserved event kind"
        )
    await _get_record(session, estimate_id)
    session.add(UiEvent(estimate_id=estimate_id, kind=payload.kind, payload=payload.payload))
    await session.commit()
    telemetry.emit_event(payload.kind, str(estimate_id), payload.payload)
    return {"status": "recorded"}


class ActualIn(BaseModel):
    work_item_id: str
    actual_effort: float = Field(gt=0)
    actual_source: Literal["timesheet", "project-report", "expert-recall"]
    completed_at: dt.date | None = None
    scope_changed: bool = False
    # Who delivered it, and in which domain. The pipeline cannot know either — a BRD
    # states what to build, not who builds it — so without these the ledger's team and
    # domain columns stay NULL on every row the product writes, and no calibration
    # slice can ever exist. Optional so existing clients keep working; the metrics
    # overview reports how many rows arrive unattributed, so "shipped" stays checkable
    # against "actually used".
    team: str | None = Field(default=None, max_length=80)
    domain_tags: list[str] | None = None


@router.post("/{estimate_id}/actuals", status_code=status.HTTP_201_CREATED)
async def record_actual_for_line(
    estimate_id: uuid.UUID, payload: ActualIn, session: SessionDep
) -> dict[str, Any]:
    """S8-1: an actual closes the loop — the signed line becomes a ledger row, its
    analogs receive outcome feedback, and the calibration state is snapshotted."""
    record = await _get_record(session, estimate_id)
    if record.boe is None:
        raise HTTPException(status_code=409, detail="no BoE draft")
    if not await _fully_signed(session, record):
        raise HTTPException(
            status_code=409, detail="actuals attach to the fully signed estimate of record"
        )
    boe = BoeDocument.model_validate(record.boe)
    line = next((line for line in boe.lines if line.work_item_id == payload.work_item_id), None)
    if line is None:
        raise HTTPException(status_code=404, detail="estimate line not found")
    state = PipelineState.model_validate(record.state)
    item = next(item for item in state.work_items if item.id == payload.work_item_id)
    try:
        await record_actual(
            session,
            estimate_id=estimate_id,
            brd_ref=record.brd_ref,
            brd_title=record.title,
            item=item,
            line=line,
            actual_effort=payload.actual_effort,
            actual_source=payload.actual_source,
            completed_at=payload.completed_at,
            scope_changed=payload.scope_changed,
            team=payload.team,
            domain_tags=payload.domain_tags,
        )
    except IntegrityError as exc:
        # Concurrent duplicate lost the check-then-insert race on origin_ref.
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="actual is being recorded concurrently; retry"
        ) from exc
    deviation = round(payload.actual_effort / line.range.likely, 2) if line.range.likely else None
    session.add(
        UiEvent(
            estimate_id=estimate_id,
            kind="actual-recorded",
            payload={
                "work_item_id": payload.work_item_id,
                "actual_source": payload.actual_source,
                "scope_changed": payload.scope_changed,
                "deviation": deviation,
            },
        )
    )
    await session.commit()
    telemetry.emit_event(
        "actual-recorded", str(estimate_id), {"work_item_id": payload.work_item_id}
    )
    return {"status": "recorded", "deviation": deviation}


@router.get("/{estimate_id}/actuals")
async def list_actuals(estimate_id: uuid.UUID, session: SessionDep) -> list[dict[str, Any]]:
    await _get_record(session, estimate_id)
    prefix = make_origin_ref(estimate_id, "")
    result = await session.execute(
        # autoescape as a matter of course: a UUID prefix cannot contain `_` or `%`,
        # but prefix matching that reasons about its input each time eventually meets
        # an input it was wrong about.
        select(LedgerEntryRow).where(LedgerEntryRow.origin_ref.startswith(prefix, autoescape=True))
    )
    entries: list[dict[str, Any]] = []
    for row in result.scalars():
        likely = float(row.est_likely) if row.est_likely else None
        actual = float(row.actual_effort) if row.actual_effort is not None else None
        entries.append(
            {
                "work_item_id": (row.origin_ref or "").removeprefix(prefix),
                "actual_effort": actual,
                "actual_source": row.actual_source,
                "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                "scope_changed": row.scope_changed,
                "team": row.team,
                "domain_tags": list(row.domain_tags or ()),
                # The band the actual was recorded AGAINST — after a rebuild the
                # current draft's band may differ; mixing the two fakes the deviation.
                "recorded_band": {
                    "optimistic": float(row.est_optimistic) if row.est_optimistic else None,
                    "likely": likely,
                    "pessimistic": float(row.est_pessimistic) if row.est_pessimistic else None,
                },
                "deviation": (round(actual / likely, 2) if actual is not None and likely else None),
            }
        )
    return entries
