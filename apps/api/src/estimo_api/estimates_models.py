"""Estimate workflow tables (S7): pipeline states, independent estimates, signatures,
UI telemetry. The BoE and pipeline state persist as JSONB snapshots of the pydantic
models — the API layer is a thin shell over the package pipeline."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from estimo_api.models import Base


class EstimateRecord(Base):
    __tablename__ = "estimates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    brd_ref: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(40))
    state: Mapped[dict[str, Any]] = mapped_column(JSONB)
    boe: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class IndependentEstimate(Base):
    """The reviewer's own band, recorded BEFORE the AI draft is revealed (PRINCIPLES #4).

    The server enforces independent-first: the desk endpoint returns the AI band for an
    item only after this row exists for the requesting estimator."""

    __tablename__ = "independent_estimates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    estimate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("estimates.id", ondelete="CASCADE"))
    work_item_id: Mapped[str] = mapped_column(String(120))
    estimator: Mapped[str] = mapped_column(String(120))
    optimistic: Mapped[float] = mapped_column(Numeric(8, 2))
    likely: Mapped[float] = mapped_column(Numeric(8, 2))
    pessimistic: Mapped[float] = mapped_column(Numeric(8, 2))
    revealed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class LineSignature(Base):
    __tablename__ = "line_signatures"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    estimate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("estimates.id", ondelete="CASCADE"))
    work_item_id: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(80))
    signed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UiEvent(Base):
    """Local telemetry capture (S7-7): correction distances, anchoring deltas.

    Forwarded to Langfuse when a live deployment configures it; the local table keeps
    the product honest offline."""

    __tablename__ = "ui_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    estimate_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("estimates.id", ondelete="SET NULL"), default=None
    )
    kind: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
