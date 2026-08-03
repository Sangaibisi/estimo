"""Sync orchestration (S9): one SyncRun per execution, checkpoint persisted as the
crawl advances so a days-long first sync survives restarts."""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Any

from estimo_code import CodeGraph, generate_module_wikis
from estimo_knowledge import upsert_document
from sqlalchemy.ext.asyncio import AsyncSession

from estimo_connectors.base import resolve_secret
from estimo_connectors.confluence import ConfluenceConnector
from estimo_connectors.db import Connection, SyncRun
from estimo_connectors.gitrepo import clone_or_fetch
from estimo_connectors.hosting import clone_username
from estimo_gateway import GatewayClient

logger = logging.getLogger("estimo.connectors.sync")

CHECKPOINT_EVERY = 25  # pages between checkpoint commits


async def run_sync(
    session: AsyncSession,
    connection: Connection,
    *,
    repos_dir: Path | None = None,
    client: GatewayClient | None = None,
) -> SyncRun:
    """Execute one sync for a connection; resumes from the last run's checkpoint."""
    previous = await _last_checkpoint(session, connection)
    run = SyncRun(connection_id=connection.id, checkpoint=dict(previous or {}))
    session.add(run)
    await session.commit()
    try:
        if connection.kind == "confluence":
            stats = await _sync_confluence(session, connection, run)
        elif connection.kind in {"bitbucket", "github", "gitlab", "git"}:
            if repos_dir is None:
                raise ValueError("repos_dir is required for git-kind connections")
            stats = await _sync_git(session, connection, run, repos_dir, client)
        else:
            raise ValueError(f"unsupported connection kind: {connection.kind}")
        run.status = "succeeded"
        run.stats = stats
    except Exception as exc:
        logger.exception("sync failed for %s", connection.name)
        run.status = "failed"
        run.error = str(exc)[:2000]
    run.finished_at = dt.datetime.now(dt.UTC)
    await session.commit()
    return run


async def _last_checkpoint(session: AsyncSession, connection: Connection) -> dict[str, Any] | None:
    from sqlalchemy import select

    last = await session.scalar(
        select(SyncRun)
        .where(SyncRun.connection_id == connection.id, SyncRun.status == "succeeded")
        .order_by(SyncRun.started_at.desc())
        .limit(1)
    )
    return dict(last.checkpoint) if last is not None and last.checkpoint else None


async def _sync_confluence(
    session: AsyncSession, connection: Connection, run: SyncRun
) -> dict[str, Any]:
    config = connection.config or {}
    token = resolve_secret(connection.secret_env)
    if not token:
        raise ValueError("confluence connection requires secret_env (API token)")
    connector = ConfluenceConnector(
        base_url=connection.base_url,
        email=str(config.get("email", "")),
        api_token=token,
        space_keys=tuple(config.get("space_keys", ())),
        default_acl=tuple(connection.acl_keys or ("public",)),
    )
    pages = 0
    checkpoint: dict[str, Any] = dict(run.checkpoint or {})
    try:
        async for document in connector.crawl(checkpoint):
            await upsert_document(
                session,
                source_type=document.source_type,
                source_ref=document.source_ref,
                title=document.title,
                text=document.text,
                acl_keys=list(document.acl_keys),
                freshness_at=document.freshness_at,
                authority=document.authority,
            )
            pages += 1
            if pages % CHECKPOINT_EVERY == 0:
                run.checkpoint = dict(checkpoint)
                await session.commit()
    finally:
        await connector.aclose()
    run.checkpoint = dict(checkpoint)
    await session.commit()
    return {"pages": pages}


async def _sync_git(
    session: AsyncSession,
    connection: Connection,
    run: SyncRun,
    repos_dir: Path,
    client: GatewayClient | None,
) -> dict[str, Any]:
    config = connection.config or {}
    token = resolve_secret(connection.secret_env)
    state = await clone_or_fetch(
        connection.base_url,
        repos_dir / connection.name,
        branch=config.get("branch"),
        username=config.get("username") or clone_username(connection.kind),
        token=token,
    )
    graph = CodeGraph.build(state.path, repo=connection.name, commit=state.head_sha)
    pages = await generate_module_wikis(graph, client=client)
    acl = list(connection.acl_keys or ["public"])
    for page in pages:
        await upsert_document(
            session,
            source_type="code-wiki",
            source_ref=page.source_ref,
            title=page.title,
            text=page.text,
            acl_keys=acl,
            freshness_at=state.head_committed_at,
            authority=0.7,
        )
    run.checkpoint = {"head_sha": state.head_sha}
    await session.commit()
    return {"modules": len(pages), "head_sha": state.head_sha}
