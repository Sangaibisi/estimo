"""multi-tenant isolation: tenant_id + row-level security + runtime app role

S10-2. Every tenant-scoped table gains a NOT NULL tenant_id (existing rows adopt the
well-known DEFAULT_TENANT, preserving single-tenant deployments) and is placed under
ENABLE + FORCE row-level security with an isolation policy keyed on the
`app.current_tenant` GUC the API sets per transaction.

A dedicated runtime role `estimo_app` (NOSUPERUSER, NOBYPASSRLS) is created and
granted DML only. Migrations run as the owner/superuser and bypass RLS; the API must
connect as `estimo_app` in a multi-tenant deployment so the policies actually bind
(a superuser connection bypasses RLS entirely — see docs/adr/0007).

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-03
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_TENANT = "00000000-0000-0000-0000-000000000000"

# Every tenant-scoped table. Ordered arbitrarily; each is handled independently.
TENANT_TABLES = (
    "runs",
    "estimates",
    "independent_estimates",
    "line_signatures",
    "ui_events",
    "ledger_entries",
    "knowledge_chunks",
    "analog_feedback",
    "calibration_snapshots",
    "connections",
    "sync_runs",
    "canonical_pages",
)

APP_ROLE = "estimo_app"


def upgrade() -> None:
    # Ongoing INSERTs adopt the request's tenant from the GUC; when the GUC is unset
    # (a raw/owner connection, e.g. migrations or the single-tenant default) they fall
    # back to DEFAULT_TENANT. This keeps WITH CHECK satisfied without every caller
    # setting tenant_id explicitly.
    guc_default = f"coalesce(current_setting('app.current_tenant', true), '{DEFAULT_TENANT}')::uuid"
    for table in TENANT_TABLES:
        op.add_column(
            table,
            sa.Column(
                "tenant_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                nullable=False,
                server_default=sa.text(f"'{DEFAULT_TENANT}'::uuid"),  # backfill existing rows
            ),
        )
        op.execute(f"ALTER TABLE {table} ALTER COLUMN tenant_id SET DEFAULT {guc_default}")
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
        # The GUC drives the policy; current_setting(..., true) is NULL when unset, so
        # an unscoped connection sees nothing (deny by default). FORCE subjects the
        # table owner too (only superusers/BYPASSRLS bypass).
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            "USING (tenant_id = current_setting('app.current_tenant', true)::uuid) "
            "WITH CHECK (tenant_id = current_setting('app.current_tenant', true)::uuid)"
        )

    # Runtime role: created idempotently, no login password baked into the migration
    # (set it out-of-band, or pass ESTIMO_APP_ROLE_PASSWORD to the migration env).
    password = os.environ.get("ESTIMO_APP_ROLE_PASSWORD", "")
    login = f"LOGIN PASSWORD '{password}'" if password else "NOLOGIN"
    op.execute(
        f"DO $$ BEGIN "
        f"IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN "
        f"CREATE ROLE {APP_ROLE} {login} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE; "
        f"END IF; END $$"
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
    # Future tables/sequences created by later migrations inherit the grants.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE}"
    )


def downgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_column(table, "tenant_id")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {APP_ROLE}")
    # The role itself is left in place (it may own nothing but dropping a granted
    # role across databases is deployment-specific).
