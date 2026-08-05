"""Tenants and user accounts (S15-1).

Two tables that deliberately sit OUTSIDE row-level security, and the reason is the
same for both: they are read *before* a tenant is known.

- `tenants` is the tenant registry. RLS on the registry itself would make "list the
  tenants" unanswerable for the platform admin, who is the only caller allowed to
  ask.
- `users` is the login identity. Authentication resolves a user from a token before
  any tenant GUC can be set, and a platform admin manages accounts across every
  tenant. So isolation here is enforced in the router layer (platform-admin-only
  routes, and every listing filtered by the caller's tenant when they are not one),
  not by a policy. `runtime_settings` is the existing precedent for a global table.

Everything a *tenant* owns — projects, the repository map, estimates, connections —
stays under the 0009 RLS pattern.
"""

from __future__ import annotations

import datetime as dt
import uuid

from estimo_knowledge.db import Base
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

# The product's three roles. Ordered most → least privileged.
#
#   platform_admin  the deployment operator: creates tenants and every user account,
#                   configures connections and the model gateway, may act inside any
#                   tenant.
#   project_owner   shapes a tenant's work: creates projects and draws the repository
#                   map, plus everything a user can do.
#   user            works the product: estimates, ledger, calibration, knowledge.
#
# Signing authority is deliberately NOT a fourth role but an orthogonal flag
# (`can_sign`): "may sign a Basis of Estimate" is a delegation that cuts across
# seniority — a plain user can hold it and a project owner can lack it.
ROLE_PLATFORM_ADMIN = "platform_admin"
ROLE_PROJECT_OWNER = "project_owner"
ROLE_USER = "user"
USER_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_PROJECT_OWNER, ROLE_USER)


class Tenant(Base):
    """One customer workspace. Every tenant-owned row keys on this id via RLS."""

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class User(Base):
    """A login identity, created by a platform admin (there is no self-registration).

    The password hash is scrypt with a per-user salt (see `passwords.py`); the column
    never leaves the API. `token_version` is bumped on password change and on
    deactivation, which invalidates every session token already issued — the one
    piece of state that makes stateless session tokens revocable.
    """

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # The user's home tenant. A platform admin has one too — it is simply not a
    # boundary for them (they may act inside any tenant via X-Estimo-Tenant).
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT")
    )
    email: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(30), default=ROLE_USER)
    can_sign: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=1)
    # Source-system audiences this person can be PROVEN to hold (Confluence space
    # keys / groups). Retrieval pre-filter input — SECURITY.md: it may only narrow.
    # NULL means "public only", never "everything".
    acl_keys: Mapped[list[str] | None] = mapped_column(JSONB, default=None)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=None)
