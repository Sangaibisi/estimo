"""Engine and session plumbing (SQLAlchemy 2 async + asyncpg)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from estimo_api.auth import Principal, current_principal
from estimo_api.settings import Settings
from estimo_api.tenancy import bind_tenant_guc, set_current_tenant


def build_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(str(settings.database_url), pool_pre_ping=True)


def build_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
) -> AsyncIterator[AsyncSession]:
    """One AsyncSession per request, scoped to the caller's tenant.

    Resolving `current_principal` first enforces auth (when enabled) and pins the
    tenant BEFORE any query runs; `bind_tenant_guc` re-applies the tenant GUC at the
    start of every transaction, so RLS isolates correctly across the several commits
    an endpoint may make. Endpoints commit explicitly; teardown rolls back leftovers.
    """
    set_current_tenant(principal.tenant)
    maker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with maker() as session:
        bind_tenant_guc(session)
        try:
            yield session
        finally:
            await session.rollback()
