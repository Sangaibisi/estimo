"""Tenants, user accounts, projects and the repository map (S15-1 / S14-1)

Two global tables (`tenants`, `users`) and three tenant-scoped ones (`projects`,
`project_repos`, `project_relations`).

`tenants` and `users` carry NO row-level security, deliberately: both are read
before a tenant is known — authentication resolves a user from a token, and the
platform admin manages accounts across every tenant. Their isolation is enforced in
the router layer. `runtime_settings` (0011) is the existing precedent. Everything a
tenant OWNS keeps the 0009 RLS pattern.

The default tenant row is seeded so single-tenant deployments — where every existing
row already carries the all-zero tenant id — have a registry entry to point at.

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_TENANT = "00000000-0000-0000-0000-000000000000"
_GUC_DEFAULT = f"coalesce(current_setting('app.current_tenant', true), '{_DEFAULT_TENANT}')::uuid"


def _tenant_column() -> sa.Column:
    return sa.Column(
        "tenant_id",
        postgresql.UUID(as_uuid=True),
        nullable=False,
        server_default=sa.text(_GUC_DEFAULT),
    )


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_tenant_isolation ON {table} "
        "USING (tenant_id = current_setting('app.current_tenant', true)::uuid) "
        "WITH CHECK (tenant_id = current_setting('app.current_tenant', true)::uuid)"
    )


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=60), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenants")),
        sa.UniqueConstraint("slug", name=op.f("uq_tenants_slug")),
    )
    op.execute(
        "INSERT INTO tenants (id, name, slug) "
        f"VALUES ('{_DEFAULT_TENANT}', 'Default workspace', 'default')"
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False, server_default="user"),
        sa.Column("can_sign", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("acl_keys", postgresql.JSONB(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_users_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])

    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        _tenant_column(),
        sa.Column("key", sa.String(length=12), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
        sa.UniqueConstraint("tenant_id", "key", name="uq_projects_tenant_key"),
    )
    op.create_index("ix_projects_tenant_id", "projects", ["tenant_id"])
    _enable_rls("projects")

    op.create_table(
        "project_repos",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        _tenant_column(),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False, server_default="git"),
        sa.Column("node_type", sa.String(length=20), nullable=False, server_default="be"),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("pos_x", sa.Float(), nullable=True),
        sa.Column("pos_y", sa.Float(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_project_repos_project_id_projects"),
            ondelete="CASCADE",
        ),
        # SET NULL, not CASCADE: deleting a connection must not delete the
        # architecture drawn around it — the node degrades to a declared repository.
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["connections.id"],
            name=op.f("fk_project_repos_connection_id_connections"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_repos")),
        sa.UniqueConstraint(
            "tenant_id", "project_id", "name", name="uq_project_repos_project_name"
        ),
    )
    op.create_index("ix_project_repos_tenant_id", "project_repos", ["tenant_id"])
    op.create_index("ix_project_repos_project_id", "project_repos", ["project_id"])
    _enable_rls("project_repos")

    op.create_table(
        "project_relations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        _tenant_column(),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_repo_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("to_repo_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False, server_default="api"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_project_relations_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["from_repo_id"],
            ["project_repos.id"],
            name=op.f("fk_project_relations_from_repo_id_project_repos"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["to_repo_id"],
            ["project_repos.id"],
            name=op.f("fk_project_relations_to_repo_id_project_repos"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_relations")),
        sa.UniqueConstraint(
            "tenant_id", "from_repo_id", "to_repo_id", "kind", name="uq_project_relations_edge"
        ),
    )
    op.create_index("ix_project_relations_tenant_id", "project_relations", ["tenant_id"])
    op.create_index("ix_project_relations_project_id", "project_relations", ["project_id"])
    _enable_rls("project_relations")


def downgrade() -> None:
    op.drop_table("project_relations")
    op.drop_table("project_repos")
    op.drop_table("projects")
    op.drop_table("users")
    op.drop_table("tenants")
