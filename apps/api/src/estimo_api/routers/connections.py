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

import httpx
from estimo_connectors import (
    CONNECTION_KINDS,
    CanonicalPage,
    Connection,
    DiscoveryUnsupported,
    SyncRun,
    approve,
    generate_candidate,
    push_event_branches,
    remote_repos,
    resolve_secret,
    run_sync,
    verify_webhook,
)
from estimo_connectors.db import PinnedSource
from estimo_connectors.pins import (
    MAX_PINS_PER_CONNECTION,
    PINNABLE_KINDS,
    fetch_pin,
    validate_pin_ref,
)
from estimo_connectors.sync import (
    STALE_RUNNING_AFTER,
    SyncAlreadyRunningError,
    effective_secret,
    sweep_interrupted_runs,
)
from estimo_knowledge import is_stale
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from estimo_api.auth import (
    Principal,
    clamp_acl_keys,
    current_principal,
    require_admin,
    require_project_owner,
    require_reviewer,
)
from estimo_api.db import get_session
from estimo_api.runtime_config import effective_gateway, gateway_client
from estimo_api.tenancy import bind_tenant_guc, get_current_tenant, set_current_tenant
from estimo_core.secrets import seal
from estimo_gateway import GatewayConfig

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
    # WRITE-ONLY panel lane (ADR-0008): the credential itself, sealed before
    # storage and never serialized back out. Wins over secret_env at sync time.
    secret: str | None = Field(default=None, min_length=1, max_length=4000)
    acl_keys: list[str] | None = None
    # S13-5: minutes between scheduled syncs; None = manual/webhook only.
    sync_cadence_minutes: int | None = Field(default=None, ge=5, le=10080)


def _connection_out(connection: Connection) -> dict[str, Any]:
    return {
        "id": str(connection.id),
        "kind": connection.kind,
        "name": connection.name,
        "base_url": connection.base_url,
        "config": connection.config,
        "secret_env": connection.secret_env,
        # True when a usable credential exists via EITHER lane; the value itself
        # never leaves the API.
        "secret_present": bool(connection.secret)
        or bool(connection.secret_env and os.getenv(connection.secret_env) is not None),
        "secret_stored": bool(connection.secret),
        "acl_keys": connection.acl_keys,
        "sync_cadence_minutes": connection.sync_cadence_minutes,
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
    if payload.secret_env is not None and payload.secret is None:
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
        secret=seal(payload.secret) if payload.secret is not None else None,
        acl_keys=payload.acl_keys,
        sync_cadence_minutes=payload.sync_cadence_minutes,
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


async def _run_sync_bg(
    sessionmaker: async_sessionmaker[AsyncSession],
    connection_id: uuid.UUID,
    gateway_config: GatewayConfig | None,
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
                client=gateway_client(gateway_config),
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
        await effective_gateway(request, session),
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
        gateway_config = await effective_gateway(request, session)
    # The sync itself runs as the app role, pinned to the connection's own tenant.
    background.add_task(
        _run_sync_bg,
        request.app.state.sessionmaker,
        connection_id,
        gateway_config,
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
async def list_canonical(
    session: SessionDep,
    principal: Annotated[Principal, Depends(current_principal)],
) -> list[dict[str, Any]]:
    """Canonical pages the caller may actually read.

    A canonical page's body is a distillation of its sources' text, so it inherits
    their audience. Before this filter existed, closing the write-side escalation was
    only half the job: any reviewer in the tenant could still read back every page,
    including ones distilled from a restricted space they have no access to.

    The audience is derived, not stored: for an approved page it is the ACL of the
    chunk that publication wrote, and for a draft it is the audience its sources share.
    A page whose sources have since been pruned has an audience that cannot be
    determined, and unknown means withheld — the row stays visible so a curator can see
    it needs regenerating, but the body does not travel.
    """
    from estimo_knowledge import KnowledgeChunk

    from estimo_core import restricting_audiences

    result = await session.execute(select(CanonicalPage).order_by(CanonicalPage.topic))
    pages = list(result.scalars())

    # Every chunk that could carry an audience for these pages, in one query: the
    # published canonical chunks, plus the source chunks the drafts point at.
    wanted: set[str] = {f"canonical://{page.topic}" for page in pages}
    for page in pages:
        wanted.update(ref.split(":", 1)[1] for ref in (page.source_refs or []) if ":" in ref)
    acl_rows = await session.execute(
        select(KnowledgeChunk.source_ref, KnowledgeChunk.acl_keys).where(
            KnowledgeChunk.source_ref.in_(wanted)
        )
    )
    acl_by_ref: dict[str, list[str]] = {ref: list(keys or []) for ref, keys in acl_rows.all()}

    def audience(page: CanonicalPage) -> set[str] | None:
        if page.status == "approved":
            published = acl_by_ref.get(f"canonical://{page.topic}")
            return set(published) if published else None
        refs = [ref.split(":", 1)[1] for ref in (page.source_refs or []) if ":" in ref]
        if not refs or any(ref not in acl_by_ref for ref in refs):
            return None  # a source vanished: the audience is unknowable
        return restricting_audiences([set(acl_by_ref[ref]) for ref in refs])

    entitled = principal.acl_keys
    audiences = {page.id: audience(page) for page in pages}

    # A page the caller shares no audience with is not listed at all. An indeterminate
    # one is listed without its body, because its existence is not the secret — its
    # text is, and a curator needs to know there is something to regenerate.
    def readable(page: CanonicalPage) -> bool:
        page_audience = audiences[page.id]
        return page_audience is None or bool(page_audience & entitled)

    pages = [page for page in pages if readable(page)]
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
            "body": page.body if audiences[page.id] is not None else None,
            # True when the sources this page was distilled from no longer resolve, so
            # no audience can be computed: the body is withheld and approval refuses.
            "sources_missing": audiences[page.id] is None,
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
        client=gateway_client(await effective_gateway(request, session)),
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


class CadenceIn(BaseModel):
    # None turns scheduling OFF for the connection — deliberate, so it is the
    # explicit body value, not an omitted field.
    sync_cadence_minutes: int | None = Field(default=None, ge=5, le=10080)


@router.get(
    "/connections/{connection_id}/remote-repos",
    dependencies=[Depends(require_project_owner)],
)
async def list_remote_repos(connection_id: uuid.UUID, session: SessionDep) -> dict[str, Any]:
    """What this connection's credential can see on its hosting server (S14).

    Project owners shape the map, so they — not only platform admins — may browse.
    The response carries names and clone URLs only; the credential itself never
    leaves the API, and the call is read-only against the remote.
    """
    connection = await session.get(Connection, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="connection not found")
    config = connection.config or {}
    token = await effective_secret(session, connection)
    try:
        scope, repos = await remote_repos(
            kind=connection.kind,
            base_url=connection.base_url,
            config=config,
            token=token,
            username=config.get("username"),
            bearer=config.get("auth") == "bearer",
        )
    except DiscoveryUnsupported as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        # Network-shaped failures are the server's, not the caller's; keep the
        # message but never the credential (httpx errors carry only the URL).
        raise HTTPException(
            status_code=502, detail=f"could not reach the hosting server: {exc}"
        ) from exc
    return {
        "connection_id": str(connection.id),
        "scope": scope,
        "repos": [
            {"slug": repo.slug, "name": repo.full_name, "clone_url": repo.clone_url}
            for repo in repos
        ],
    }


@router.patch("/connections/{connection_id}", dependencies=[Depends(require_admin)])
async def update_cadence(
    connection_id: uuid.UUID, payload: CadenceIn, session: SessionDep
) -> dict[str, Any]:
    """S13-5: the scheduler cadence is panel-managed per connection."""
    connection = await session.get(Connection, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="connection not found")
    connection.sync_cadence_minutes = payload.sync_cadence_minutes
    await session.commit()
    await session.refresh(connection)
    return _connection_out(connection)


class PinIn(BaseModel):
    ref: str = Field(min_length=1, max_length=200)


def _pin_out(pin: PinnedSource) -> dict[str, Any]:
    return {
        "id": str(pin.id),
        "kind": pin.kind,
        "ref": pin.ref,
        "created_by": pin.created_by,
        "created_at": pin.created_at.isoformat() if pin.created_at else None,
        "last_synced_at": pin.last_synced_at.isoformat() if pin.last_synced_at else None,
        "last_error": pin.last_error,
    }


@router.get("/connections/{connection_id}/pins")
async def list_pins(connection_id: uuid.UUID, session: SessionDep) -> list[dict[str, Any]]:
    if await session.get(Connection, connection_id) is None:
        raise HTTPException(status_code=404, detail="connection not found")
    pins = (
        (
            await session.execute(
                select(PinnedSource)
                .where(PinnedSource.connection_id == connection_id)
                .order_by(PinnedSource.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_pin_out(pin) for pin in pins]


@router.post(
    "/connections/{connection_id}/pins",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_reviewer)],
)
async def create_pin(
    connection_id: uuid.UUID,
    payload: PinIn,
    session: SessionDep,
    principal: Annotated[Principal, Depends(current_principal)],
) -> dict[str, Any]:
    """S13-5 "pin this source now": page ID / issue key → the connector's own
    single-item fetch (ACL-walked, version-pinned) → upsert, synchronously — the
    caller learns in this response whether the source actually landed. The pin
    then joins the connection's re-sync set (every successful sync re-fetches it).
    """
    connection = await session.get(Connection, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="connection not found")
    try:
        ref = validate_pin_ref(connection.kind, payload.ref)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    count = await session.scalar(
        select(func.count(PinnedSource.id)).where(PinnedSource.connection_id == connection_id)
    )
    if int(count or 0) >= MAX_PINS_PER_CONNECTION:
        raise HTTPException(
            status_code=409,
            detail=f"pin limit reached ({MAX_PINS_PER_CONNECTION}); curation, not mirroring",
        )
    existing = await session.scalar(
        select(PinnedSource).where(
            PinnedSource.connection_id == connection_id, PinnedSource.ref == ref
        )
    )
    pin = existing or PinnedSource(
        connection_id=connection_id,
        kind=PINNABLE_KINDS[connection.kind],
        ref=ref,
        created_by=principal.subject,
    )
    if existing is None:
        session.add(pin)
    await fetch_pin(session, connection, pin)
    await session.commit()
    await session.refresh(pin)
    return _pin_out(pin)


@router.delete(
    "/connections/{connection_id}/pins/{pin_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
async def delete_pin(connection_id: uuid.UUID, pin_id: uuid.UUID, session: SessionDep) -> None:
    """Unpinning stops the refresh; it deliberately does NOT delete the ingested
    chunk — removing knowledge from retrieval is a curation decision, not a
    side effect of tidying a pin list."""
    pin = await session.get(PinnedSource, pin_id)
    if pin is None or pin.connection_id != connection_id:
        raise HTTPException(status_code=404, detail="pin not found")
    await session.delete(pin)
    await session.commit()
