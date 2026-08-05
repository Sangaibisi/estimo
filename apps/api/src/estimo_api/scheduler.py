"""Per-connection sync scheduler (S13-5).

An in-process asyncio loop, not a worker service: ADR-0006 keeps the default
deployment at exactly {db, migrate, api, web}, and a cadence measured in minutes
does not justify a fifth container. Consequences, stated rather than hidden:

- The tick enumerates connections through the SYSTEM sessionmaker (RLS-exempt) —
  the same cross-tenant pattern the webhook path uses — then runs each sync
  pinned to its connection's tenant.
- Multiple replicas each run a scheduler. The partial unique index (one running
  sync per connection) makes the duplicate attempt fail cleanly with
  SyncAlreadyRunningError; a few wasted wakeups are the accepted cost.
- A FAILED run still counts as an attempt: due-ness is measured from the last
  run's start of ANY status, so a permanently broken connection retries once per
  cadence, not once per tick.
- `sync_cadence_minutes IS NULL` is the off switch. There is no separate enabled
  flag to drift from it, and no environment variable — the panel manages this
  (ADR-0008).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import uuid
from typing import Any

from estimo_connectors import Connection, SyncRun
from sqlalchemy import func, select

from estimo_gateway import deployment_gateway_config

logger = logging.getLogger("estimo.api.scheduler")

TICK_SECONDS = 60.0


async def due_connection_ids(session: Any, now: dt.datetime) -> list[tuple[uuid.UUID, str]]:
    """(connection_id, tenant_id) pairs whose cadence has elapsed.

    `session` must be SYSTEM (RLS-exempt) — an app-role session would only ever
    see one tenant's connections and silently never schedule the rest.
    """
    last_started = (
        select(
            SyncRun.connection_id,
            func.max(SyncRun.started_at).label("last_started"),
        )
        .group_by(SyncRun.connection_id)
        .subquery()
    )
    rows = await session.execute(
        select(
            Connection.id,
            Connection.tenant_id,
            Connection.sync_cadence_minutes,
            last_started.c.last_started,
        )
        .join(last_started, last_started.c.connection_id == Connection.id, isouter=True)
        .where(Connection.sync_cadence_minutes.is_not(None))
    )
    due: list[tuple[uuid.UUID, str]] = []
    for connection_id, tenant_id, cadence, started in rows:
        if started is None or started <= now - dt.timedelta(minutes=int(cadence)):
            due.append((connection_id, str(tenant_id)))
    return due


async def tick(app: Any, *, now: dt.datetime | None = None) -> list[uuid.UUID]:
    """One scheduler pass; returns the connection ids it attempted."""
    from estimo_api.routers.connections import _run_sync_bg

    now = now or dt.datetime.now(tz=dt.UTC)
    async with app.state.system_sessionmaker() as session:
        due = await due_connection_ids(session, now)
    if not due:
        return []
    # The panel override wins over env exactly as it does on the request path.
    gateway = await deployment_gateway_config(app.state.engine)
    attempted: list[uuid.UUID] = []
    for connection_id, tenant in due:
        # Sequential on purpose: a tick that wakes five overdue connections must
        # not open five clones/crawls at once on a single API process.
        try:
            await _run_sync_bg(app.state.sessionmaker, connection_id, gateway, tenant)
            attempted.append(connection_id)
        except Exception:
            logger.exception("scheduled sync failed for connection %s", connection_id)
    return attempted


async def scheduler_loop(app: Any) -> None:
    """Started from the lifespan; cancelled on shutdown."""
    logger.info("sync scheduler started (tick %.0fs)", TICK_SECONDS)
    while True:
        await asyncio.sleep(TICK_SECONDS)
        try:
            await tick(app)
        except asyncio.CancelledError:
            raise
        except Exception:
            # One bad tick (DB restart, transient network) must not kill the
            # scheduler for the process lifetime.
            logger.exception("scheduler tick failed")
