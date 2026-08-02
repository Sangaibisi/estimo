"""Engine and session plumbing (SQLAlchemy 2 async + asyncpg)."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from estimo_api.settings import Settings


def build_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(str(settings.database_url), pool_pre_ping=True)


def build_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One AsyncSession per request. Endpoints commit explicitly; teardown only
    rolls back leftovers (it runs after the response is sent)."""
    maker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with maker() as session:
        try:
            yield session
        finally:
            await session.rollback()
