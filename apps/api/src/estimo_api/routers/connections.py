"""Admin → Connections (S9): sources, syncs, webhooks, canonical curation.

Secrets follow the env-indirection rule: the API accepts and returns only the NAME
of the env var holding a credential (SECURITY.md; ADR-0006 env-only config).

AuthZ (S10): mutations require the `admin` role and canonical curation the
`reviewer` role; the webhook receiver is authenticated by HMAC, not a bearer token.
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
from estimo_connectors.sync import (
    STALE_RUNNING_AFTER,
    SyncAlreadyRunningError,
    sweep_interrupted_runs,
)
from estimo_knowledge import is_stale
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from estimo_api.auth import (
    Principal,
    clamp_acl_keys,
    current_principal,
    require_admin,
    require_reviewer,
)
from estimo_api.db import get_session
from estimo_api.settings import Settings
from estimo_api.tenancy import bind_tenant_guc, get_current_tenant, set_current_tenant
from estimo_gateway import GatewayClient

router = APIRouter(prefix="/v1", tags=["connections"])
# The webhook receiver authenticates by HMAC over the raw body, not a bearer
# token — a git host has no user identity — so it is mounted WITHOUT the
# role dependency the rest of this surface carries.
webhook_router = APIRouter(prefix="/v1", tags=["connections"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _repos_dir() -> Path:
    # Read at call time (tests/deploys override the env after import); the default
    # matches the path the image prepares with app-user ownership.
    return Path(os.environ.get("ESTIMO_REPOS_DIR", "/data/repos"))


class ConnectionIn(BaseModel):
    kind: str = Field(pattern="^(" + "|".join(CONNECTION_KINDS) + ")$")
    # The name feeds a working-tree directory name; keep it path-safe at the
    # boundary (defense in depth — sync also slugs it).
    name: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9._ -]*$")
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


@router.post(
    "/connections", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)]
)
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


@router.delete(
    "/connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
async def delete_connection(connection_id: uuid.UUID, session: SessionDep) -> None:
    connection = await session.get(Connection, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="connection not found")
    await session.delete(connection)
    await session.commit()


def _gateway_client(settings: Settings) -> GatewayClient | None:
    """Best-effort gateway for distillation/wiki generation; connectors degrade to
    deterministic skeletons when the gateway is unreachable."""
    try:
        return GatewayClient(settings.gateway)
    except Exception:  # noqa: BLE001 - observability of the LLM leg must not block sync
        return None


async def _run_sync_bg(
    sessionmaker: async_sessionmaker[AsyncSession],
    connection_id: uuid.UUID,
    settings: Settings,
    tenant: str,
) -> None:
    # A background task runs outside the request, so pin the tenant explicitly (the
    # triggering request supplied it) before opening the tenant-scoped session.
    set_current_tenant(tenant)
    async with sessionmaker() as session:
        bind_tenant_guc(session)
        connection = await session.get(Connection, connection_id)
        if connection is None:
            return
        try:
            await run_sync(
                session,
                connection,
                repos_dir=_repos_dir(),
                client=_gateway_client(settings),
            )
        except SyncAlreadyRunningError:
            # The DB-level guard (one running run per connection) already refused
            # the duplicate — e.g. a webhook burst; nothing to do.
            return


@router.post(
    "/connections/{connection_id}/sync",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_admin)],
)
async def trigger_sync(
    connection_id: uuid.UUID,
    session: SessionDep,
    request: Request,
    background: BackgroundTasks,
) -> dict[str, str]:
    connection = await session.get(Connection, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="connection not found")
    # Self-heal: an orphaned 'running' row (crashed process) is swept here — visible
    # to this tenant under RLS — so a stuck row never wedges syncs, even without the
    # startup janitor (which is a system/owner path in multi-tenant).
    await sweep_interrupted_runs(session, older_than=STALE_RUNNING_AFTER)
    running = await session.scalar(
        select(SyncRun).where(SyncRun.connection_id == connection_id, SyncRun.status == "running")
    )
    if running is not None:
        raise HTTPException(status_code=409, detail="a sync is already running")
    background.add_task(
        _run_sync_bg,
        request.app.state.sessionmaker,
        connection_id,
        request.app.state.settings,
        get_current_tenant(),
    )
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


@webhook_router.post("/webhooks/{connection_id}", status_code=status.HTTP_202_ACCEPTED)
async def receive_webhook(
    connection_id: uuid.UUID,
    request: Request,
    background: BackgroundTasks,
) -> dict[str, str]:
    """Push-event receiver: verified against the RAW body, then an incremental
    re-index is scheduled. Verified by HMAC, NOT by a bearer token — the external git
    host has no user identity — so this route does not use the auth'd session.

    Multi-tenant (S10): the connection is looked up by its opaque UUID across tenants,
    which requires an RLS-exempt connection — the SYSTEM sessionmaker (the owner URL
    when `ESTIMO_OWNER_DATABASE_URL` is set; otherwise the app connection, correct in
    single-tenant). The background sync is then pinned to the connection's own tenant.
    """
    system_sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.system_sessionmaker
    async with system_sessionmaker() as session:
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
        tenant = str(connection.tenant_id)
    # The sync itself runs as the app role, pinned to the connection's own tenant.
    background.add_task(
        _run_sync_bg,
        request.app.state.sessionmaker,
        connection_id,
        request.app.state.settings,
        tenant,
    )
    return {"status": "scheduled"}


# ---- Canonical pages curation (S9-4) ----


class CandidateIn(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    acl_keys: list[str] | None = None


class ApproveIn(BaseModel):
    approver: str = Field(min_length=1, max_length=120)
    # Required when the sources share no common ACL audience (mixed visibility) —
    # the approver states who may read the page; defaulting to public would widen.
    acl_keys: list[str] | None = None


@router.get("/canonical")
async def list_canonical(session: SessionDep) -> list[dict[str, Any]]:
    from estimo_knowledge import KnowledgeChunk

    result = await session.execute(select(CanonicalPage).order_by(CanonicalPage.topic))
    pages = list(result.scalars())
    # Staleness follows the published chunk, which carries the OLDEST SOURCE's
    # freshness — curation time would hide a page built on stale sources.
    freshness_rows = await session.execute(
        select(KnowledgeChunk.source_ref, KnowledgeChunk.freshness_at).where(
            KnowledgeChunk.source_type == "canonical"
        )
    )
    chunk_freshness: dict[str, Any] = {ref: freshness for ref, freshness in freshness_rows.all()}
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
            "stale": is_stale(
                chunk_freshness.get(f"canonical://{page.topic}", page.updated_at)
                if page.status == "approved"
                else page.updated_at
            ),
            "updated_at": page.updated_at.isoformat(),
        }
        for page in pages
    ]


@router.post(
    "/canonical", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_reviewer)]
)
async def create_candidate(
    payload: CandidateIn,
    session: SessionDep,
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
) -> dict[str, str]:
    # The body's acl_keys select WHICH of the caller's own audiences to search; they
    # never grant one. Unclamped, this endpoint was a read primitive for any
    # restricted chunk in the tenant (the excerpts land in page.body, which
    # GET /v1/canonical hands back).
    page = await generate_candidate(
        session,
        topic=payload.topic,
        acl_keys=clamp_acl_keys(principal, payload.acl_keys),
        client=_gateway_client(request.app.state.settings),
    )
    await session.commit()
    return {"id": str(page.id), "status": page.status}


@router.post("/canonical/{page_id}/approve", dependencies=[Depends(require_reviewer)])
async def approve_candidate(
    page_id: uuid.UUID,
    payload: ApproveIn,
    session: SessionDep,
    principal: Annotated[Principal, Depends(current_principal)],
) -> dict[str, Any]:
    page = await session.get(CanonicalPage, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="canonical page not found")
    try:
        page = await approve(
            session,
            page,
            approver=payload.approver,
            acl_keys=(
                clamp_acl_keys(principal, payload.acl_keys)
                if payload.acl_keys is not None
                else None
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return {"id": str(page.id), "status": page.status, "version": page.version}
