"""connectors: connections, sync runs, canonical pages

S9: live-knowledge sources (Confluence, Bitbucket-first git hosting, Jira) and the
canonical-pages curation flow. Secrets never land in these tables — connections
reference the NAME of an environment variable.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "connections",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("config", JSONB, nullable=False),
        sa.Column("secret_env", sa.String(length=120), nullable=True),
        sa.Column("acl_keys", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connections")),
        sa.UniqueConstraint("name", name=op.f("uq_connections_name")),
    )
    op.create_table(
        "sync_runs",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("checkpoint", JSONB, nullable=True),
        sa.Column("stats", JSONB, nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_runs")),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["connections.id"],
            name=op.f("fk_sync_runs_connection_id_connections"),
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_sync_runs_connection_id", "sync_runs", ["connection_id"])
    op.create_table(
        "canonical_pages",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("topic", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("approved_by", sa.String(length=120), nullable=True),
        sa.Column("source_refs", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_canonical_pages")),
        sa.UniqueConstraint("topic", name=op.f("uq_canonical_pages_topic")),
    )


def downgrade() -> None:
    op.drop_table("canonical_pages")
    op.drop_index("ix_sync_runs_connection_id", table_name="sync_runs")
    op.drop_table("sync_runs")
    op.drop_table("connections")
