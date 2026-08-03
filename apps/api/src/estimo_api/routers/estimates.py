"""Estimate workflow endpoints (S7 backend).

Independent-first is SERVER-enforced (PRINCIPLES #4): the desk endpoint returns an
item's AI band only after the requesting estimator has recorded their own band for it —
the client cannot leak the draft early even if buggy. Anchors stay visible here
(humans see them); only model boundaries redact.
"""

from __future__ import annotations

import io
import tempfile
import uuid
from pathlib import Path
from typing import Annotated, Any

from estimo_estimate import estimate_state, render_boe_docx, review_boe
from estimo_pipeline import PipelineState, resume_with_answers, run_brd
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimo_api.db import get_session
from estimo_api.estimates_models import (
    EstimateRecord,
    IndependentEstimate,
    LineSignature,
    UiEvent,
)
from estimo_core import BoeDocument

router = APIRouter(prefix="/v1/estimates", tags=["estimates"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


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


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_estimate(file: UploadFile, session: SessionDep) -> EstimateSummary:
    if not (file.filename or "").lower().endswith(".docx"):
        raise HTTPException(status_code=422, detail="a .docx BRD is required")
    payload = await file.read()
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="BRD exceeds the 20 MB limit")
    with tempfile.TemporaryDirectory() as tmp:
        brd_path = Path(tmp) / (Path(file.filename or "brd.docx").name)
        brd_path.write_bytes(payload)
        try:
            state = await run_brd(brd_path, thread_id=f"api-{uuid.uuid4()}")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    record = EstimateRecord(
        brd_ref=state.parsed.brd_ref if state.parsed else brd_path.stem,
        title=state.parsed.title if state.parsed else brd_path.stem,
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
    return {
        "summary": _summary(record).model_dump(mode="json"),
        "state": record.state,
        "boe": record.boe,
    }


class AnswersIn(BaseModel):
    answers: dict[str, str]


@router.post("/{estimate_id}/answers")
async def apply_answers(
    estimate_id: uuid.UUID, payload: AnswersIn, session: SessionDep
) -> EstimateSummary:
    record = await _get_record(session, estimate_id)
    state = PipelineState.model_validate(record.state)
    try:
        state = await resume_with_answers(state, payload.answers)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record.state = state.model_dump(mode="json")
    record.status = state.status
    record.boe = None  # answers invalidate any previous draft
    await session.commit()
    await session.refresh(record)
    return _summary(record)


@router.post("/{estimate_id}/estimate")
async def build_boe(estimate_id: uuid.UUID, session: SessionDep) -> dict[str, Any]:
    record = await _get_record(session, estimate_id)
    state = PipelineState.model_validate(record.state)
    try:
        boe = await estimate_state(session, state)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    findings = review_boe(boe, state)
    # Computed fields (total) serialize but are rejected on re-validation
    # (extra="forbid") — persist the storable projection only.
    record.boe = boe.model_dump(mode="json", exclude={"total"})
    record.status = "boe_draft"
    await session.commit()
    return {"boe": record.boe, "critic": findings}


class IndependentIn(BaseModel):
    work_item_id: str
    estimator: str = Field(min_length=1, max_length=120)
    optimistic: float = Field(ge=0)
    likely: float = Field(ge=0)
    pessimistic: float = Field(ge=0)


@router.post("/{estimate_id}/independent", status_code=status.HTTP_201_CREATED)
async def record_independent(
    estimate_id: uuid.UUID, payload: IndependentIn, session: SessionDep
) -> dict[str, str]:
    if not payload.optimistic <= payload.likely <= payload.pessimistic:
        raise HTTPException(status_code=422, detail="band must be ordered o <= l <= p")
    record = await _get_record(session, estimate_id)
    state = PipelineState.model_validate(record.state)
    if payload.work_item_id not in {item.id for item in state.work_items}:
        raise HTTPException(status_code=404, detail="work item not found")
    existing = await session.scalar(
        select(IndependentEstimate).where(
            IndependentEstimate.estimate_id == estimate_id,
            IndependentEstimate.work_item_id == payload.work_item_id,
            IndependentEstimate.estimator == payload.estimator,
        )
    )
    if existing is not None:
        # Immutable by design: revising the independent value after seeing the draft
        # would defeat the anchoring telemetry.
        raise HTTPException(status_code=409, detail="independent estimate already recorded")
    session.add(
        IndependentEstimate(
            estimate_id=estimate_id,
            work_item_id=payload.work_item_id,
            estimator=payload.estimator,
            optimistic=payload.optimistic,
            likely=payload.likely,
            pessimistic=payload.pessimistic,
        )
    )
    session.add(
        UiEvent(
            estimate_id=estimate_id,
            kind="independent-recorded",
            payload={"work_item_id": payload.work_item_id, "estimator": payload.estimator},
        )
    )
    await session.commit()
    return {"status": "recorded"}


@router.get("/{estimate_id}/desk")
async def estimate_desk(
    estimate_id: uuid.UUID,
    session: SessionDep,
    estimator: Annotated[str, Query(min_length=1)],
) -> dict[str, Any]:
    """Independent-first desk: AI bands appear per item ONLY after the estimator's own
    band exists for that item (server-enforced, PRINCIPLES #4)."""
    record = await _get_record(session, estimate_id)
    state = PipelineState.model_validate(record.state)
    boe = BoeDocument.model_validate(record.boe) if record.boe else None
    lines_by_item = {line.work_item_id: line for line in (boe.lines if boe else ())}

    independents = {
        row.work_item_id: row
        for row in (
            await session.execute(
                select(IndependentEstimate).where(
                    IndependentEstimate.estimate_id == estimate_id,
                    IndependentEstimate.estimator == estimator,
                )
            )
        ).scalars()
    }
    signatures = {
        row.work_item_id
        for row in (
            await session.execute(
                select(LineSignature).where(LineSignature.estimate_id == estimate_id)
            )
        ).scalars()
    }

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
            "signed": item.id in signatures,
            "ai": None,
            "delta_likely": None,
        }
        if independent is not None and line is not None:
            entry["ai"] = line.model_dump(mode="json")
            entry["delta_likely"] = round(float(independent.likely) - line.range.likely, 1)
            if not independent.revealed:
                independent.revealed = True
                session.add(
                    UiEvent(
                        estimate_id=estimate_id,
                        kind="draft-revealed",
                        payload={
                            "work_item_id": item.id,
                            "estimator": estimator,
                            "delta_likely": entry["delta_likely"],
                        },
                    )
                )
        items.append(entry)
    await session.commit()
    return {"items": items, "has_boe": boe is not None}


class SignIn(BaseModel):
    work_item_id: str
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=80)


@router.post("/{estimate_id}/sign", status_code=status.HTTP_201_CREATED)
async def sign_line(estimate_id: uuid.UUID, payload: SignIn, session: SessionDep) -> dict[str, str]:
    record = await _get_record(session, estimate_id)
    if record.boe is None:
        raise HTTPException(status_code=409, detail="no BoE draft to sign")
    boe = BoeDocument.model_validate(record.boe)
    if payload.work_item_id not in {line.work_item_id for line in boe.lines}:
        raise HTTPException(status_code=404, detail="estimate line not found")
    session.add(
        LineSignature(
            estimate_id=estimate_id,
            work_item_id=payload.work_item_id,
            name=payload.name,
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
    boe = BoeDocument.model_validate(record.boe)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "boe.docx"
        render_boe_docx(boe, out)
        content = out.read_bytes()
    return StreamingResponse(
        io.BytesIO(content),
        media_type=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        headers={"Content-Disposition": f'attachment; filename="{record.brd_ref}-boe.docx"'},
    )


class EventIn(BaseModel):
    kind: str = Field(min_length=1, max_length=60)
    payload: dict[str, Any] | None = None


@router.post("/{estimate_id}/events", status_code=status.HTTP_201_CREATED)
async def record_event(
    estimate_id: uuid.UUID, payload: EventIn, session: SessionDep
) -> dict[str, str]:
    await _get_record(session, estimate_id)
    session.add(UiEvent(estimate_id=estimate_id, kind=payload.kind, payload=payload.payload))
    await session.commit()
    return {"status": "recorded"}
