"""BoE version history + a document-level signature (S12-5)

Two things the design assumes and the schema did not support:

- **Version history.** `boe_version` was an integer counter and `record.boe` was
  overwritten on every rebuild, so "Diff v2 → v3" had nothing to diff and the
  document a customer was shown could not be reconstructed after a rebuild. A BoE is
  the artifact the estimate exists to produce; overwriting it is the one thing a
  record of that kind must not do.
- **A two-role flow.** `line_signatures` covers ROWS, which is right for a reviewer,
  but a signing authority signs the document — the whole scope, once. Modelling that
  as one signature per row would misstate what was signed.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-04
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# Must match estimo_knowledge.db.DEFAULT_TENANT — a different constant here would
# file every row of these two tables under a tenant nothing else can see.
DEFAULT_TENANT = "00000000-0000-0000-0000-000000000000"
TENANT_DEFAULT = f"coalesce(current_setting('app.current_tenant', true), '{DEFAULT_TENANT}')::uuid"

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "boe_versions",
        sa.Column("id", sa.Uuid(), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            nullable=False,
            server_default=sa.text(TENANT_DEFAULT),
        ),
        sa.Column(
            "estimate_id",
            sa.Uuid(),
            sa.ForeignKey("estimates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("document", JSONB, nullable=False),
        sa.Column("critic", JSONB, nullable=True),
        sa.Column("note", sa.String(300), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("estimate_id", "version", name="uq_boe_versions_estimate_version"),
    )
    op.create_table(
        "document_signatures",
        sa.Column("id", sa.Uuid(), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            nullable=False,
            server_default=sa.text(TENANT_DEFAULT),
        ),
        sa.Column(
            "estimate_id",
            sa.Uuid(),
            sa.ForeignKey("estimates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("boe_version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("role", sa.String(80), nullable=False),
        sa.Column(
            "signed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "estimate_id", "boe_version", "role", name="uq_document_signatures_version_role"
        ),
    )
    # Same tenancy treatment as every other tenant table (ADR-0007).
    for table in ("boe_versions", "document_signatures"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            "USING (tenant_id = current_setting('app.current_tenant', true)::uuid) "
            "WITH CHECK (tenant_id = current_setting('app.current_tenant', true)::uuid)"
        )

    # Backfill: an estimate that already carries a draft has a current version with no
    # snapshot, so its history would be permanently missing the one version anyone is
    # looking at — and every derived flag (authority signed? diffable?) would read
    # false forever on exactly the estimates a deployment already has.
    op.execute(
        """
        INSERT INTO boe_versions (id, tenant_id, estimate_id, version, document, critic, note)
        SELECT gen_random_uuid(), tenant_id, id, boe_version, boe, critic,
               'snapshot taken at migration 0014'
        FROM estimates
        WHERE boe IS NOT NULL AND boe_version > 0
        """
    )

    # A duplicate line signature was possible: nothing stopped the same signer from
    # signing one row twice, and the export then names them twice.
    op.create_unique_constraint(
        "uq_line_signatures_item_signer_version",
        "line_signatures",
        ["estimate_id", "work_item_id", "boe_version", "name"],
    )

    # 0009's ALTER DEFAULT PRIVILEGES only covers objects created by the role that ran
    # it, so grant explicitly — but only if the role exists: single-tenant deployments
    # never create it, and an unconditional GRANT would abort their migration.
    role_exists = (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'estimo_app'"))
        .first()
    )
    if role_exists:
        for table in ("boe_versions", "document_signatures"):
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO estimo_app")


def downgrade() -> None:
    op.drop_constraint("uq_line_signatures_item_signer_version", "line_signatures", type_="unique")
    op.drop_table("document_signatures")
    op.drop_table("boe_versions")
