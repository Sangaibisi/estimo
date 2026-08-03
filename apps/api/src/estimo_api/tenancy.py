"""Multi-tenant isolation (S10-2) — RLS-backed, defense-in-depth.

Web-verified design (2026): Row-Level Security is the database-enforced BACKSTOP on
top of application scoping, never instead of it. The tenant is set per request as a
TRANSACTION-LOCAL GUC via `set_config('app.current_tenant', :tenant, true)` — bind
parameter (no string interpolation), auto-cleared by Postgres on commit/rollback, so
it cannot leak across pooled connections the way a session-scoped SET would.

Because the app commits several times per request, the GUC is (re)applied at the
start of every transaction via a SQLAlchemy `after_begin` event driven by a
ContextVar — one set-up point, correct across every commit in the request.

The runtime DB role is NOSUPERUSER / NOBYPASSRLS; migrations run as the owner role
that may bypass RLS. A single well-known DEFAULT_TENANT preserves single-tenant
(auth-disabled) deployments: every historical row belongs to it.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from sqlalchemy import Connection, event, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

# Stable UUID for the implicit tenant of a single-tenant deployment.
DEFAULT_TENANT = "00000000-0000-0000-0000-000000000000"

_current_tenant: ContextVar[str] = ContextVar("estimo_current_tenant", default=DEFAULT_TENANT)


def set_current_tenant(tenant: str) -> None:
    _current_tenant.set(tenant)


def get_current_tenant() -> str:
    return _current_tenant.get()


def _apply_tenant_guc(session: Session, transaction: Any, connection: Connection) -> None:
    # Runs at the start of every transaction. Issue the SET on the CONNECTION the
    # event hands us, not via session.execute — the session is mid-provisioning here
    # and a re-entrant session op would raise "concurrent operations not permitted".
    connection.execute(
        text("SELECT set_config('app.current_tenant', :tenant, true)"),
        {"tenant": _current_tenant.get()},
    )


def bind_tenant_guc(session: AsyncSession) -> None:
    """Attach the per-transaction tenant GUC to an async session's sync backer."""
    event.listen(session.sync_session, "after_begin", _apply_tenant_guc)
