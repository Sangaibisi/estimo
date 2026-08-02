"""Run records: minimal S1 surface (create / read / list)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimo_api.db import get_session
from estimo_api.models import Run

router = APIRouter(prefix="/v1/runs", tags=["runs"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class RunCreate(BaseModel):
    kind: str = Field(min_length=1, max_length=50)
    detail: dict[str, Any] | None = None


class RunOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    detail: dict[str, Any] | None
    created_at: dt.datetime
    updated_at: dt.datetime

    model_config = {"from_attributes": True}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_run(payload: RunCreate, session: SessionDep) -> RunOut:
    run = Run(kind=payload.kind, detail=payload.detail)
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return RunOut.model_validate(run)


@router.get("/{run_id}")
async def get_run(run_id: uuid.UUID, session: SessionDep) -> RunOut:
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return RunOut.model_validate(run)


@router.get("")
async def list_runs(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[RunOut]:
    result = await session.execute(select(Run).order_by(Run.created_at.desc()).limit(limit))
    return [RunOut.model_validate(run) for run in result.scalars()]
