"""estimate ledger + knowledge chunks (Turkish FTS, dimension-flexible embeddings)

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR, UUID

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ledger_entries",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("brd_ref", sa.String(length=120), nullable=False),
        sa.Column("brd_title", sa.String(length=300), nullable=True),
        sa.Column("customer", sa.String(length=120), nullable=True),
        sa.Column("item_title", sa.String(length=300), nullable=False),
        sa.Column("item_description", sa.Text(), nullable=True),
        sa.Column("module_tags", ARRAY(sa.String(length=60)), nullable=False),
        sa.Column("domain_tags", ARRAY(sa.String(length=60)), nullable=False),
        sa.Column("team", sa.String(length=80), nullable=True),
        sa.Column("est_optimistic", sa.Numeric(8, 2), nullable=True),
        sa.Column("est_likely", sa.Numeric(8, 2), nullable=True),
        sa.Column("est_pessimistic", sa.Numeric(8, 2), nullable=True),
        sa.Column("estimate_single", sa.Numeric(8, 2), nullable=True),
        sa.Column("estimated_at", sa.Date(), nullable=True),
        sa.Column("method", sa.String(length=30), nullable=True),
        sa.Column("actual_effort", sa.Numeric(8, 2), nullable=True),
        sa.Column("actual_source", sa.String(length=30), nullable=True),
        sa.Column("completed_at", sa.Date(), nullable=True),
        sa.Column("scope_changed", sa.Boolean(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.VECTOR(), nullable=True),
        sa.Column("embedding_model", sa.String(length=120), nullable=True),
        sa.Column("embedding_dim", sa.Integer(), nullable=True),
        sa.Column(
            "search_tsv",
            TSVECTOR(),
            sa.Computed(
                "to_tsvector('turkish', coalesce(item_title, '') || ' ' || "
                "coalesce(item_description, ''))",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ledger_entries")),
    )
    op.create_index(
        "ix_ledger_entries_search_tsv",
        "ledger_entries",
        ["search_tsv"],
        postgresql_using="gin",
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("source_ref", sa.String(length=500), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("acl_keys", ARRAY(sa.String(length=80)), nullable=False),
        sa.Column("freshness_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("authority", sa.Float(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.VECTOR(), nullable=True),
        sa.Column("embedding_model", sa.String(length=120), nullable=True),
        sa.Column("embedding_dim", sa.Integer(), nullable=True),
        sa.Column(
            "search_tsv",
            TSVECTOR(),
            sa.Computed(
                "to_tsvector('turkish', coalesce(title, '') || ' ' || coalesce(text, ''))",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_chunks")),
    )
    op.create_index(
        "ix_knowledge_chunks_search_tsv",
        "knowledge_chunks",
        ["search_tsv"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_knowledge_chunks_acl_keys",
        "knowledge_chunks",
        ["acl_keys"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_table("knowledge_chunks")
    op.drop_table("ledger_entries")
