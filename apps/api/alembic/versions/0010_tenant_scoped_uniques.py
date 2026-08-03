"""tenant-scoped unique constraints

S10 review fix: RLS restricts row VISIBILITY but Postgres evaluates unique indexes
across ALL rows regardless of policy. A global unique key on a tenant table lets one
tenant's write collide with (or, via ON CONFLICT upsert, overwrite) another tenant's
row and leaks existence. Every such key becomes composite with tenant_id.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # connections.name
    op.drop_constraint("uq_connections_name", "connections", type_="unique")
    op.create_unique_constraint("uq_connections_tenant_name", "connections", ["tenant_id", "name"])
    # canonical_pages.topic
    op.drop_constraint("uq_canonical_pages_topic", "canonical_pages", type_="unique")
    op.create_unique_constraint(
        "uq_canonical_pages_tenant_topic", "canonical_pages", ["tenant_id", "topic"]
    )
    # knowledge_chunks (source_type, source_ref) — this one backs an ON CONFLICT upsert.
    op.drop_index("uq_knowledge_chunks_source", table_name="knowledge_chunks")
    op.create_index(
        "uq_knowledge_chunks_source",
        "knowledge_chunks",
        ["tenant_id", "source_type", "source_ref"],
        unique=True,
    )
    # ledger_entries.origin_ref
    op.drop_index("uq_ledger_entries_origin_ref", table_name="ledger_entries")
    op.create_index(
        "uq_ledger_entries_origin_ref",
        "ledger_entries",
        ["tenant_id", "origin_ref"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_ledger_entries_origin_ref", table_name="ledger_entries")
    op.create_index("uq_ledger_entries_origin_ref", "ledger_entries", ["origin_ref"], unique=True)
    op.drop_index("uq_knowledge_chunks_source", table_name="knowledge_chunks")
    op.create_index(
        "uq_knowledge_chunks_source",
        "knowledge_chunks",
        ["source_type", "source_ref"],
        unique=True,
    )
    op.drop_constraint("uq_canonical_pages_tenant_topic", "canonical_pages", type_="unique")
    op.create_unique_constraint("uq_canonical_pages_topic", "canonical_pages", ["topic"])
    op.drop_constraint("uq_connections_tenant_name", "connections", type_="unique")
    op.create_unique_constraint("uq_connections_name", "connections", ["name"])
