"""Knowledge-layer tables: the estimate ledger and the generic retrieval chunks.

Both tables carry a PostgreSQL `turkish`-configured generated tsvector (the lexical
retrieval leg — snowball stemming verified against the pgvector image) and a
dimension-flexible embedding column with its model id and dimension recorded per row
(a customer swapping embedding models must never silently mix vector spaces).
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    Boolean,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from estimo_core.models import SQL_NAMING_CONVENTION


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=SQL_NAMING_CONVENTION)


# Stable UUID of the implicit tenant for single-tenant / auth-disabled deployments.
DEFAULT_TENANT = "00000000-0000-0000-0000-000000000000"

_TENANT_DEFAULT = text(
    f"coalesce(current_setting('app.current_tenant', true), '{DEFAULT_TENANT}')::uuid"
)


class TenantScoped:
    """Mixin: every tenant-owned table carries a tenant_id under row-level security
    (S10-2). The DB default resolves the current-tenant GUC, so application code never
    has to thread the tenant through inserts."""

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=_TENANT_DEFAULT, nullable=False
    )


class LedgerEntryRow(TenantScoped, Base):
    """One historical work item: estimate given, actual outcome (docs/LEDGER-SCHEMA.md)."""

    __tablename__ = "ledger_entries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    brd_ref: Mapped[str] = mapped_column(String(120))
    brd_title: Mapped[str | None] = mapped_column(String(300), default=None)
    customer: Mapped[str | None] = mapped_column(String(120), default=None)
    item_title: Mapped[str] = mapped_column(String(300))
    item_description: Mapped[str | None] = mapped_column(Text, default=None)
    module_tags: Mapped[list[str]] = mapped_column(ARRAY(String(60)), default=list)
    domain_tags: Mapped[list[str]] = mapped_column(ARRAY(String(60)), default=list)
    team: Mapped[str | None] = mapped_column(String(80), default=None)

    est_optimistic: Mapped[float | None] = mapped_column(Numeric(8, 2), default=None)
    est_likely: Mapped[float | None] = mapped_column(Numeric(8, 2), default=None)
    est_pessimistic: Mapped[float | None] = mapped_column(Numeric(8, 2), default=None)
    estimate_single: Mapped[float | None] = mapped_column(Numeric(8, 2), default=None)
    estimated_at: Mapped[dt.date | None] = mapped_column(Date, default=None)
    method: Mapped[str | None] = mapped_column(String(30), default=None)

    actual_effort: Mapped[float | None] = mapped_column(Numeric(8, 2), default=None)
    actual_source: Mapped[str | None] = mapped_column(String(30), default=None)
    completed_at: Mapped[dt.date | None] = mapped_column(Date, default=None)
    scope_changed: Mapped[bool] = mapped_column(Boolean, default=False)

    # Provenance for rows written by the product itself (S8 loop):
    # "estimate://{estimate_id}/{work_item_id}". NULL for imported history.
    origin_ref: Mapped[str | None] = mapped_column(String(200), default=None)

    embedding: Mapped[Any | None] = mapped_column(VECTOR, default=None)
    embedding_model: Mapped[str | None] = mapped_column(String(120), default=None)
    embedding_dim: Mapped[int | None] = mapped_column(Integer, default=None)

    search_tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('turkish', coalesce(item_title, '') || ' ' || "
            "coalesce(item_description, ''))",
            persisted=True,
        ),
    )

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_ledger_entries_search_tsv", "search_tsv", postgresql_using="gin"),
        # Unique PER TENANT — an origin_ref is only meaningful within a tenant.
        Index("uq_ledger_entries_origin_ref", "tenant_id", "origin_ref", unique=True),
    )


class AnalogFeedback(TenantScoped, Base):
    """Outcome feedback on an analog's usefulness (S8-2, PRINCIPLES #8).

    Written by the calibration loop when an actual lands: the analogs that backed a
    line (its `ledger://` evidence) receive a weight from the line's realized error.
    `find_analogs` folds the cumulative weight into ranking — analogs that keep
    backing bad bands sink; ones that back accurate bands rise."""

    __tablename__ = "analog_feedback"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    entry_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ledger_entries.id", ondelete="CASCADE"))
    origin_ref: Mapped[str] = mapped_column(String(200))
    weight: Mapped[float] = mapped_column(Numeric(6, 3))
    reason: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        # One verdict per (analog, estimated line): re-recording an actual revises
        # instead of stacking duplicate weight.
        Index("uq_analog_feedback_entry_origin", "entry_id", "origin_ref", unique=True),
    )


class CalibrationSnapshot(TenantScoped, Base):
    """Point-in-time calibration state (S8-2/S8-3): quantiles of the transfer-error
    distribution plus rolling empirical coverage — the drift signal the dashboard
    plots against the nominal band."""

    __tablename__ = "calibration_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    samples: Mapped[int] = mapped_column(Integer)
    prior_based: Mapped[bool] = mapped_column(Boolean, default=False)
    q10: Mapped[float] = mapped_column(Numeric(8, 3))
    q50: Mapped[float] = mapped_column(Numeric(8, 3))
    q90: Mapped[float] = mapped_column(Numeric(8, 3))
    nominal: Mapped[float] = mapped_column(Numeric(4, 2), default=0.8)
    rolling_coverage: Mapped[float | None] = mapped_column(Numeric(4, 3), default=None)
    # How many rows THAT rate was computed from. `samples` above is the transfer
    # distribution's count over a different population; pairing it with this rate
    # rendered a 3-row 33% coverage as "33% · n=33". NULL on snapshots written before
    # migration 0016 — unrecoverable, and inventing one is the failure this screen
    # exists to avoid.
    rolling_samples: Mapped[int | None] = mapped_column(Integer, default=None)
    trigger: Mapped[str] = mapped_column(String(60), default="actual-recorded")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class KnowledgeChunk(TenantScoped, Base):
    """Generic retrieval unit for the wiki/code shelves (populated from S5/S9 on).

    ACL keys are enforced as a retrieval PRE-filter (SECURITY.md); freshness/authority
    feed ranking.
    """

    __tablename__ = "knowledge_chunks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_type: Mapped[str] = mapped_column(String(30))
    source_ref: Mapped[str] = mapped_column(String(500))
    title: Mapped[str | None] = mapped_column(String(300), default=None)
    text: Mapped[str] = mapped_column(Text)
    acl_keys: Mapped[list[str]] = mapped_column(ARRAY(String(80)), default=lambda: ["public"])
    freshness_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    authority: Mapped[float] = mapped_column(Float, default=0.5)

    embedding: Mapped[Any | None] = mapped_column(VECTOR, default=None)
    embedding_model: Mapped[str | None] = mapped_column(String(120), default=None)
    embedding_dim: Mapped[int | None] = mapped_column(Integer, default=None)

    search_tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('turkish', coalesce(title, '') || ' ' || coalesce(text, ''))",
            persisted=True,
        ),
    )

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_knowledge_chunks_search_tsv", "search_tsv", postgresql_using="gin"),
        Index("ix_knowledge_chunks_acl_keys", "acl_keys", postgresql_using="gin"),
        # Unique PER TENANT and the ON CONFLICT target for chunk upserts.
        Index(
            "uq_knowledge_chunks_source",
            "tenant_id",
            "source_type",
            "source_ref",
            unique=True,
        ),
    )
