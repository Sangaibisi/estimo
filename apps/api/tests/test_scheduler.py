"""The sync scheduler (S13-5): due-ness math and the tick's dispatch."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import pytest
from estimo_connectors import Connection, SyncRun
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from estimo_api import scheduler

pytestmark = pytest.mark.db


@pytest.fixture
async def clean(session: AsyncSession, clean_tables: None) -> AsyncSession:
    await session.execute(text("TRUNCATE connections, sync_runs, pinned_sources CASCADE"))
    await session.commit()
    return session


def _connection(name: str, cadence: int | None) -> Connection:
    return Connection(
        kind="git",
        name=name,
        base_url="file:///tmp/none",
        config={},
        sync_cadence_minutes=cadence,
    )


class TestDueness:
    async def test_cadence_null_is_never_scheduled(self, clean: AsyncSession) -> None:
        clean.add(_connection("manual-only", None))
        await clean.commit()
        due = await scheduler.due_connection_ids(clean, dt.datetime.now(tz=dt.UTC))
        assert due == []

    async def test_a_connection_with_no_runs_is_due(self, clean: AsyncSession) -> None:
        connection = _connection("fresh", 30)
        clean.add(connection)
        await clean.commit()
        due = await scheduler.due_connection_ids(clean, dt.datetime.now(tz=dt.UTC))
        assert [pair[0] for pair in due] == [connection.id]

    async def test_a_recent_run_of_any_status_defers_the_next_attempt(
        self, clean: AsyncSession
    ) -> None:
        connection = _connection("recently-failed", 30)
        clean.add(connection)
        await clean.commit()
        # A FAILED run still counts: without this, a permanently broken connection
        # would retry every tick instead of once per cadence.
        clean.add(SyncRun(connection_id=connection.id, status="failed"))
        await clean.commit()
        now = dt.datetime.now(tz=dt.UTC)
        assert await scheduler.due_connection_ids(clean, now) == []
        later = now + dt.timedelta(minutes=31)
        assert [p[0] for p in await scheduler.due_connection_ids(clean, later)] == [connection.id]


class _FakeApp:
    def __init__(self, sessionmaker: Any, engine: Any) -> None:
        self.state = type(
            "S",
            (),
            {
                "sessionmaker": sessionmaker,
                "system_sessionmaker": sessionmaker,
                "engine": engine,
            },
        )()


class TestTick:
    async def test_the_tick_dispatches_exactly_the_due_connections(
        self, clean: AsyncSession, database_url: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        due_connection = _connection("due", 15)
        clean.add(due_connection)
        clean.add(_connection("manual", None))
        await clean.commit()

        dispatched: list[tuple[uuid.UUID, str]] = []

        async def _recorder(
            sessionmaker: Any, connection_id: uuid.UUID, gateway: Any, tenant: str
        ) -> None:
            dispatched.append((connection_id, tenant))

        from estimo_api.routers import connections as connections_module

        monkeypatch.setattr(connections_module, "_run_sync_bg", _recorder)

        engine = create_async_engine(database_url)
        try:
            maker = async_sessionmaker(engine, expire_on_commit=False)
            app = _FakeApp(maker, engine)
            attempted = await scheduler.tick(app)
        finally:
            await engine.dispose()

        assert attempted == [due_connection.id]
        assert [pair[0] for pair in dispatched] == [due_connection.id]
        # The tenant rode along — a scheduler that loses it would sync into the
        # wrong (or no) tenant under RLS.
        assert dispatched[0][1] == str(due_connection.tenant_id)
