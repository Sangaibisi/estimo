"""Estimate workflow tables (S7): pipeline states, independent estimates, signatures,
UI telemetry. The BoE and pipeline state persist as JSONB snapshots of the pydantic
models — the API layer is a thin shell over the package pipeline."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from estimo_knowledge.db import TenantScoped
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from estimo_api.models import Base


class EstimateRecord(TenantScoped, Base):
    __tablename__ = "estimates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Optimistic lock. `state` is one JSONB document that every workflow endpoint
    # reads, mutates in Python and writes back WHOLE, so two overlapping requests
    # both read the pre-image and the second erases the first — silently, with both
    # callers getting 200. SQLAlchemy adds `WHERE state_version = <read value>` to
    # every UPDATE of this row and raises StaleDataError when it matches nothing,
    # which the app turns into a 409. Broader than locking each endpoint: it also
    # covers writers that do not exist yet.
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    brd_ref: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(40))
    state: Mapped[dict[str, Any]] = mapped_column(JSONB)
    boe: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    # Bumped on every build. Independent bands and signatures are stamped with the
    # version they were recorded against, so a rebuilt draft never inherits reveals
    # or sign-offs from a dead draft.
    boe_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    critic: Mapped[list[str] | None] = mapped_column(JSONB, default=None)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __mapper_args__ = {"version_id_col": state_version}  # noqa: RUF012


class IndependentEstimate(TenantScoped, Base):
    """The reviewer's own band, recorded BEFORE the AI draft is revealed (PRINCIPLES #4).

    The server enforces independent-first: the desk endpoint returns the AI band for an
    item only after this row exists for the requesting estimator."""

    __tablename__ = "independent_estimates"
    __table_args__ = (
        UniqueConstraint(
            "estimate_id",
            "work_item_id",
            "estimator",
            "boe_version",
            name="uq_independent_estimates_item_estimator_version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    estimate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("estimates.id", ondelete="CASCADE"))
    work_item_id: Mapped[str] = mapped_column(String(120))
    estimator: Mapped[str] = mapped_column(String(120))
    boe_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    optimistic: Mapped[float] = mapped_column(Numeric(8, 2))
    likely: Mapped[float] = mapped_column(Numeric(8, 2))
    pessimistic: Mapped[float] = mapped_column(Numeric(8, 2))
    # Why this band, in the estimator's words. Optional, captured at entry — the delta
    # to the draft records how far apart the two were, never what the human knew.
    rationale: Mapped[str | None] = mapped_column(Text, default=None)
    revealed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class LineSignature(TenantScoped, Base):
    __tablename__ = "line_signatures"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    estimate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("estimates.id", ondelete="CASCADE"))
    work_item_id: Mapped[str] = mapped_column(String(120))
    boe_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(80))
    signed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UiEvent(TenantScoped, Base):
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
