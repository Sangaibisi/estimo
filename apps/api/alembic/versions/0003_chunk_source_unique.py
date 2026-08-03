"""unique (source_type, source_ref) on knowledge_chunks

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Dedupe first (keep the newest row per source), then back the invariant with the DB.
    op.execute(
        """
        DELETE FROM knowledge_chunks older
        USING knowledge_chunks newer
        WHERE older.source_type = newer.source_type
          AND older.source_ref = newer.source_ref
          AND (older.created_at, older.id) < (newer.created_at, newer.id)
        """
    )
    op.create_index(
        "uq_knowledge_chunks_source",
        "knowledge_chunks",
        ["source_type", "source_ref"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_knowledge_chunks_source", table_name="knowledge_chunks")
