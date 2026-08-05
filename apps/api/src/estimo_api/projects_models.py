"""Projects and the repository map (S14-1).

The map that shipped as a UI-only surface becomes server state here: a project owns
repository nodes and the directed relations between them. Two kinds of node share
one table on purpose —

- a node with `connection_id` is a SYNCED repository: its name, provider and code
  graph come from the connection, and the map only adds placement and typing;
- a node without one is DECLARED: a repository someone drew because it exists in the
  architecture even though Estimo does not (yet) index it.

Both are first-class relation endpoints, because the architecture does not care
which ones we happen to have credentials for. Everything is tenant-scoped under the
0009 RLS pattern.
"""

from __future__ import annotations

import datetime as dt
import uuid

from estimo_knowledge.db import Base, TenantScoped
from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

# Architectural layer of a node. The map lays these out in columns, and S14-2 will
# read them as discipline priors (client/middleware → frontend, service/data →
# backend), so the vocabulary is closed rather than free text.
NODE_TYPES = ("fe", "mobile", "middleware", "be", "db", "lib", "infra")

# What one repository does to another. `api` = a call at runtime, `data` = a shared
# store or feed. Both are directed: the arrow points at the dependency.
RELATION_KINDS = ("api", "data")


class Project(TenantScoped, Base):
    """A named piece of the tenant's landscape, owned by a project owner."""

    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_projects_tenant_key"),
        Index("ix_projects_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(12))
    name: Mapped[str] = mapped_column(String(120))
    # The account answerable for this map. Nullable so a project survives the
    # deletion of the account that made it — an orphaned map is still the truth
    # about the architecture.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProjectRepo(TenantScoped, Base):
    """One repository node on a project's map."""

    __tablename__ = "project_repos"
    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "name", name="uq_project_repos_project_name"),
        Index("ix_project_repos_tenant_id", "tenant_id"),
        Index("ix_project_repos_project_id", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(200))
    provider: Mapped[str] = mapped_column(String(20), default="git")
    node_type: Mapped[str] = mapped_column(String(20), default="be")
    # Set when this node IS a synced connection. ON DELETE SET NULL: removing the
    # connection must not silently delete the architecture drawn around it — the
    # node stays as a declared repository and the relations survive.
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connections.id", ondelete="SET NULL"), default=None
    )
    # NULL = auto-layout by architectural layer. A dragged node stores its point.
    pos_x: Mapped[float | None] = mapped_column(Float, default=None)
    pos_y: Mapped[float | None] = mapped_column(Float, default=None)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ProjectRelation(TenantScoped, Base):
    """A directed edge between two nodes of the SAME project."""

    __tablename__ = "project_relations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "from_repo_id",
            "to_repo_id",
            "kind",
            name="uq_project_relations_edge",
        ),
        Index("ix_project_relations_tenant_id", "tenant_id"),
        Index("ix_project_relations_project_id", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    from_repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_repos.id", ondelete="CASCADE")
    )
    to_repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_repos.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(10), default="api")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
