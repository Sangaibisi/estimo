"""Shared api-test fixtures (used where a test file doesn't define its own)."""

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

ALEMBIC_INI = Path(__file__).parents[1] / "alembic.ini"

_TENANT_TABLES = (
    "estimates",
    "ledger_entries",
    "knowledge_chunks",
    "calibration_snapshots",
    "connections",
    "sync_runs",
    "canonical_pages",
    "runs",
    # Deployment config, not tenant data — but it leaks between tests exactly like
    # tenant data does: a panel-saved gateway from one test made the next one see a
    # configured deployment it never configured.
    "runtime_settings",
    # Accounts and the repository map (S14-1 / S15-1). `users` in particular decides
    # whether the API is in its open first-run state, so a leftover account from one
    # test would 401 every request in the next.
    "project_relations",
    "project_repos",
    "projects",
    "users",
    "tenants",
)

# TRUNCATE takes the seeded default workspace with it; every account references one,
# so it is put back rather than left for each test to rediscover.
_DEFAULT_TENANT = "00000000-0000-0000-0000-000000000000"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    url = os.environ["ESTIMO_TEST_DATABASE_URL"]
    os.environ["ESTIMO_DATABASE_URL"] = url
    command.upgrade(Config(str(ALEMBIC_INI)), "head")
    yield url


@pytest.fixture
async def clean_tables(database_url: str) -> AsyncIterator[None]:
    engine = create_async_engine(database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        await session.execute(text(f"TRUNCATE {', '.join(_TENANT_TABLES)} CASCADE"))
        await session.execute(
            text(
                "INSERT INTO tenants (id, name, slug) "
                f"VALUES ('{_DEFAULT_TENANT}', 'Default workspace', 'default')"
            )
        )
        await session.commit()
    yield
    await engine.dispose()


@pytest.fixture
async def session(database_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as sess:
        yield sess
    await engine.dispose()
