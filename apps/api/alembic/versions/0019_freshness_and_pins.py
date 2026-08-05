"""Sync cadence + pinned sources (S13-5)

Per-connection scheduler cadence (`connections.sync_cadence_minutes`, NULL = the
existing manual/webhook-only behaviour — the column IS the switch) and the
`pinned_sources` table backing the "pin this source now" primitive: a page ID or
issue key fetched through the existing single-item REST path, re-fetched on every
successful sync of its connection so a pin can never go permanently stale behind
the incremental crawl's watermark.

Tenant-scoped with the 0009 RLS pattern.

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_TENANT = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    op.add_column("connections", sa.Column("sync_cadence_minutes", sa.Integer(), nullable=True))
    guc_default = (
        f"coalesce(current_setting('app.current_tenant', true), '{_DEFAULT_TENANT}')::uuid"
    )
    op.create_table(
        "pinned_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text(guc_default),
        ),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("ref", sa.String(length=200), nullable=False),
        sa.Column("created_by", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["connections.id"],
            name=op.f("fk_pinned_sources_connection_id_connections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pinned_sources")),
        sa.UniqueConstraint(
            "tenant_id", "connection_id", "ref", name="uq_pinned_sources_tenant_connection_ref"
        ),
    )
    op.create_index("ix_pinned_sources_tenant_id", "pinned_sources", ["tenant_id"])
    op.execute("ALTER TABLE pinned_sources ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE pinned_sources FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY pinned_sources_tenant_isolation ON pinned_sources "
        "USING (tenant_id = current_setting('app.current_tenant', true)::uuid) "
        "WITH CHECK (tenant_id = current_setting('app.current_tenant', true)::uuid)"
    )


def downgrade() -> None:
    op.drop_table("pinned_sources")
    op.drop_column("connections", "sync_cadence_minutes")
