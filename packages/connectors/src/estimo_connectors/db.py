"""Connector-layer tables (S9): configured connections, sync runs, canonical pages.

Secrets are NEVER stored: a connection references the NAME of an environment
variable (`secret_env`) the operator sets on the container (ADR-0006 env-only
config; SECURITY.md). The database holds only non-secret coordinates.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from estimo_knowledge.db import Base, TenantScoped
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

CONNECTION_KINDS = ("confluence", "bitbucket", "github", "gitlab", "git", "jira")


class Connection(TenantScoped, Base):
    """One configured external source (Admin → Connections)."""

    __tablename__ = "connections"
    # Unique PER TENANT — a global unique name would collide/leak across tenants.
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_connections_tenant_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120))
    base_url: Mapped[str] = mapped_column(String(500))
    # Non-secret coordinates: space keys, workspace/repo slugs, JQL, branch, …
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # NAME of the env var holding the credential — never the credential itself.
    secret_env: Mapped[str | None] = mapped_column(String(120), default=None)
    # ACL keys stamped onto every chunk this connection ingests (retrieval
    # pre-filter input, SECURITY.md).
    acl_keys: Mapped[list[str] | None] = mapped_column(JSONB, default=None)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SyncRun(TenantScoped, Base):
    """One (possibly checkpoint-resumed) sync execution of a connection."""

    __tablename__ = "sync_runs"
    __table_args__ = (
        Index("ix_sync_runs_connection_id", "connection_id"),
        # Concurrency guard: at most one running sync per connection — every entry
        # point (manual trigger, webhook, scheduler) inherits it via run_sync.
        Index(
            "uq_sync_runs_one_running",
            "connection_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(20), default="running")
    # Resumable cursor state: v2 cursor / last-modified watermark / repo SHAs.
    checkpoint: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class CanonicalPage(TenantScoped, Base):
    """Curated distillation (S9-4): candidate → human approval → versioned page.

    Approved pages enter retrieval as high-authority chunks; draft candidates
    never do — curation is a human gate, not a suggestion."""

    __tablename__ = "canonical_pages"
    __table_args__ = (
        UniqueConstraint("tenant_id", "topic", name="uq_canonical_pages_tenant_topic"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    topic: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    version: Mapped[int] = mapped_column(Integer, default=1)
    approved_by: Mapped[str | None] = mapped_column(String(120), default=None)
    # Provenance: the chunk/page URIs the distillation drew from.
    source_refs: Mapped[list[str] | None] = mapped_column(JSONB, default=None)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
