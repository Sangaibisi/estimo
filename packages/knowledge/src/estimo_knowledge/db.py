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
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from estimo_core.models import SQL_NAMING_CONVENTION


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=SQL_NAMING_CONVENTION)


class LedgerEntryRow(Base):
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

    __table_args__ = (Index("ix_ledger_entries_search_tsv", "search_tsv", postgresql_using="gin"),)


class KnowledgeChunk(Base):
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
        Index("uq_knowledge_chunks_source", "source_type", "source_ref", unique=True),
    )
