"""Admin → Connections (S9): sources, syncs, webhooks, canonical curation.

Secrets follow the env-indirection rule: the API accepts and returns only the NAME
of the env var holding a credential (SECURITY.md; ADR-0006 env-only config).

Known residual (S10 authN/Z): this surface is admin-shaped but unauthenticated
until OIDC lands — deployments must keep the API loopback/private until then.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Annotated, Any

from estimo_connectors import (
    CONNECTION_KINDS,
    CanonicalPage,
    Connection,
    SyncRun,
    approve,
    generate_candidate,
    push_event_branches,
    resolve_secret,
    run_sync,
    verify_webhook,
)
from estimo_knowledge import is_stale
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from estimo_api.db import get_session

router = APIRouter(prefix="/v1", tags=["connections"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

REPOS_DIR = Path(os.environ.get("ESTIMO_REPOS_DIR", "/tmp/estimo-repos"))


class ConnectionIn(BaseModel):
    kind: str = Field(pattern="^(" + "|".join(CONNECTION_KINDS) + ")$")
    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=1, max_length=500)
    config: dict[str, Any] = Field(default_factory=dict)
    secret_env: str | None = Field(default=None, max_length=120)
    acl_keys: list[str] | None = None


def _connection_out(connection: Connection) -> dict[str, Any]:
    return {
        "id": str(connection.id),
        "kind": connection.kind,
        "name": connection.name,
        "base_url": connection.base_url,
        "config": connection.config,
        "secret_env": connection.secret_env,
        "secret_present": bool(
            connection.secret_env and os.getenv(connection.secret_env) is not None
        ),
        "acl_keys": connection.acl_keys,
    }


@router.get("/connections")
async def list_connections(session: SessionDep) -> list[dict[str, Any]]:
    result = await session.execute(select(Connection).order_by(Connection.created_at))
    connections = []
    for connection in result.scalars():
        latest = await session.scalar(
            select(SyncRun)
            .where(SyncRun.connection_id == connection.id)
            .order_by(SyncRun.started_at.desc())
            .limit(1)
        )
        entry = _connection_out(connection)
        entry["last_run"] = (
            {
                "status": latest.status,
                "started_at": latest.started_at.isoformat(),
                "finished_at": latest.finished_at.isoformat() if latest.finished_at else None,
                "stats": latest.stats,
                "error": latest.error,
            }
            if latest
            else None
        )
        connections.append(entry)
    return connections


@router.post("/connections", status_code=status.HTTP_201_CREATED)
async def create_connection(payload: ConnectionIn, session: SessionDep) -> dict[str, Any]:
    if payload.secret_env is not None:
        try:
            resolve_secret(payload.secret_env)
        except LookupError as exc:
            # Fail at configuration time, not at 2 AM sync time.
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    connection = Connection(
        kind=payload.kind,
        name=payload.name,
        base_url=payload.base_url,
        config=payload.config,
        secret_env=payload.secret_env,
        acl_keys=payload.acl_keys,
    )
    session.add(connection)
    await session.commit()
    await session.refresh(connection)
    return _connection_out(connection)


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(connection_id: uuid.UUID, session: SessionDep) -> None:
    connection = await session.get(Connection, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="connection not found")
    await session.delete(connection)
    await session.commit()


async def _run_sync_bg(
    sessionmaker: async_sessionmaker[AsyncSession], connection_id: uuid.UUID
) -> None:
    async with sessionmaker() as session:
        connection = await session.get(Connection, connection_id)
        if connection is not None:
            await run_sync(session, connection, repos_dir=REPOS_DIR)


@router.post("/connections/{connection_id}/sync", status_code=status.HTTP_202_ACCEPTED)
async def trigger_sync(
    connection_id: uuid.UUID,
    session: SessionDep,
    request: Request,
    background: BackgroundTasks,
) -> dict[str, str]:
    connection = await session.get(Connection, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="connection not found")
    running = await session.scalar(
        select(SyncRun).where(SyncRun.connection_id == connection_id, SyncRun.status == "running")
    )
    if running is not None:
        raise HTTPException(status_code=409, detail="a sync is already running")
    background.add_task(_run_sync_bg, request.app.state.sessionmaker, connection_id)
    return {"status": "scheduled"}


@router.get("/connections/{connection_id}/runs")
async def list_runs(connection_id: uuid.UUID, session: SessionDep) -> list[dict[str, Any]]:
    result = await session.execute(
        select(SyncRun)
        .where(SyncRun.connection_id == connection_id)
        .order_by(SyncRun.started_at.desc())
        .limit(20)
    )
    return [
        {
            "id": str(run.id),
            "status": run.status,
            "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "checkpoint": run.checkpoint,
            "stats": run.stats,
            "error": run.error,
        }
        for run in result.scalars()
    ]


@router.post("/webhooks/{connection_id}", status_code=status.HTTP_202_ACCEPTED)
async def receive_webhook(
    connection_id: uuid.UUID,
    session: SessionDep,
    request: Request,
    background: BackgroundTasks,
) -> dict[str, str]:
    """Push-event receiver: verified against the RAW body, then an incremental
    re-index is scheduled. Unverifiable deliveries are rejected — a webhook with no
    configured secret is a misconfiguration, not a pass."""
    connection = await session.get(Connection, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="connection not found")
    secret_env = (connection.config or {}).get("webhook_secret_env")
    secret = os.getenv(secret_env) if secret_env else None
    if not secret:
        raise HTTPException(status_code=422, detail="webhook secret is not configured")
    body = await request.body()
    if not verify_webhook(connection.kind, dict(request.headers), body, secret):
        raise HTTPException(status_code=401, detail="webhook signature verification failed")
    payload = await request.json() if body else {}
    branches = push_event_branches(connection.kind, payload)
    configured_branch = (connection.config or {}).get("branch")
    if configured_branch and branches and configured_branch not in branches:
        return {"status": "ignored"}  # push to a branch we do not index
    background.add_task(_run_sync_bg, request.app.state.sessionmaker, connection_id)
    return {"status": "scheduled"}


# ---- Canonical pages curation (S9-4) ----


class CandidateIn(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    acl_keys: list[str] | None = None


class ApproveIn(BaseModel):
    approver: str = Field(min_length=1, max_length=120)


@router.get("/canonical")
async def list_canonical(session: SessionDep) -> list[dict[str, Any]]:
    result = await session.execute(select(CanonicalPage).order_by(CanonicalPage.topic))
    return [
        {
            "id": str(page.id),
            "topic": page.topic,
            "title": page.title,
            "body": page.body,
            "status": page.status,
            "version": page.version,
            "approved_by": page.approved_by,
            "source_refs": page.source_refs,
            "stale": is_stale(page.updated_at),
            "updated_at": page.updated_at.isoformat(),
        }
        for page in result.scalars()
    ]


@router.post("/canonical", status_code=status.HTTP_201_CREATED)
async def create_candidate(payload: CandidateIn, session: SessionDep) -> dict[str, str]:
    page = await generate_candidate(session, topic=payload.topic, acl_keys=payload.acl_keys)
    await session.commit()
    return {"id": str(page.id), "status": page.status}


@router.post("/canonical/{page_id}/approve")
async def approve_candidate(
    page_id: uuid.UUID, payload: ApproveIn, session: SessionDep
) -> dict[str, Any]:
    page = await session.get(CanonicalPage, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="canonical page not found")
    page = await approve(session, page, approver=payload.approver)
    await session.commit()
    return {"id": str(page.id), "status": page.status, "version": page.version}
