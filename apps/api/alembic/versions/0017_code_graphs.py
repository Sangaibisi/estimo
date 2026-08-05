"""Persist the CodeGraph a git sync builds (S13-2)

Sync built a per-repo CodeGraph on every run, used it to generate module wiki
pages, and discarded it — while the one consumer that wanted it, the estimator's
impact evidence, never received a graph in the deployed path (`estimate_state` was
always called with `graph=None`). One row per (tenant, connection), replaced in
place on re-sync: keying on the commit would orphan the previous graph on every
push the way the commit-embedded code-wiki refs already churn.

Tenant-scoped with the 0009 RLS pattern: the graph is derived from a tenant's own
repository and symbol names are content.

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Matches DEFAULT_TENANT in estimo_knowledge.db / migration 0009.
_DEFAULT_TENANT = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    guc_default = (
        f"coalesce(current_setting('app.current_tenant', true), '{_DEFAULT_TENANT}')::uuid"
    )
    op.create_table(
        "code_graphs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text(guc_default),
        ),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("repo", sa.String(length=120), nullable=False),
        sa.Column("commit", sa.String(length=80), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("stats", postgresql.JSONB(), nullable=True),
        sa.Column(
            "built_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["connections.id"],
            name=op.f("fk_code_graphs_connection_id_connections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_code_graphs")),
        sa.UniqueConstraint("tenant_id", "connection_id", name="uq_code_graphs_tenant_connection"),
    )
    op.create_index("ix_code_graphs_tenant_id", "code_graphs", ["tenant_id"])
    op.execute("ALTER TABLE code_graphs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE code_graphs FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY code_graphs_tenant_isolation ON code_graphs "
        "USING (tenant_id = current_setting('app.current_tenant', true)::uuid) "
        "WITH CHECK (tenant_id = current_setting('app.current_tenant', true)::uuid)"
    )


def downgrade() -> None:
    op.drop_table("code_graphs")
