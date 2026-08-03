"""Sync orchestration (S9): one SyncRun per execution, checkpoint persisted as the
crawl advances so a days-long first sync survives restarts.

Concurrency: a partial unique index (one `running` row per connection, migration
0008) makes starting a second concurrent sync an IntegrityError instead of a race —
the manual trigger, the webhook path, and any future scheduler all funnel through
`run_sync` and inherit the guarantee. Interrupted runs are swept to `failed` at API
startup so a crashed container never blocks future syncs.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import re
from pathlib import Path
from typing import Any

from estimo_code import CodeGraph, generate_module_wikis
from estimo_knowledge import KnowledgeChunk, embed_pending, upsert_document
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from estimo_connectors.base import connection_secret
from estimo_connectors.confluence import ConfluenceConnector
from estimo_connectors.db import Connection, SyncRun
from estimo_connectors.gitrepo import clone_or_fetch
from estimo_connectors.hosting import clone_username
from estimo_connectors.jira import JiraConnector
from estimo_gateway import GatewayClient

logger = logging.getLogger("estimo.connectors.sync")

CHECKPOINT_EVERY = 25  # pages between checkpoint commits
# A 'running' row older than this is treated as orphaned (crashed process) and swept
# on the next trigger, so a stuck row never wedges a tenant's syncs indefinitely.
STALE_RUNNING_AFTER = dt.timedelta(hours=1)

_PATH_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


class SyncAlreadyRunningError(RuntimeError):
    pass


def _workdir_name(connection: Connection) -> str:
    """Filesystem-safe working-tree name: the display name is user input and must
    not become a path component verbatim ('..', '/', …)."""
    slug = _PATH_SAFE.sub("_", connection.name).strip("._") or "repo"
    return f"{slug}-{str(connection.id)[:8]}"


async def sweep_interrupted_runs(
    session: AsyncSession, *, older_than: dt.timedelta | None = None
) -> int:
    """Mark `running` runs as failed. A killed container leaves them running forever,
    which would 409-block future syncs. `older_than` limits the sweep to clearly
    orphaned rows (used by the per-tenant self-heal on trigger); None sweeps all
    (startup janitor, run as a system/owner session across tenants)."""
    predicate = SyncRun.status == "running"
    if older_than is not None:
        cutoff = dt.datetime.now(dt.UTC) - older_than
        predicate = predicate & (SyncRun.started_at < cutoff)
    result = await session.execute(
        update(SyncRun)
        .where(predicate)
        .values(
            status="failed",
            error="interrupted (process restarted mid-sync)",
            finished_at=dt.datetime.now(dt.UTC),
        )
    )
    await session.commit()
    return int(getattr(result, "rowcount", 0) or 0)


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
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise SyncAlreadyRunningError(f"a sync is already running for {connection.name}") from exc
    try:
        if connection.kind == "confluence":
            stats = await _sync_confluence(session, connection, run)
        elif connection.kind == "jira":
            stats = await _sync_jira(session, connection, run)
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
        # The session may be in a failed transaction; roll back BEFORE the
        # bookkeeping writes or the failure record itself fails.
        await session.rollback()
        run.status = "failed"
        run.error = str(exc)[:2000]
        session.add(run)
    run.finished_at = dt.datetime.now(dt.UTC)
    await session.commit()

    # Embedding is a best-effort enrichment and runs only once the run's terminal
    # state is DURABLE. A gateway outage must not cost the expensive, rate-limited
    # part — the crawl — and must not be able to disturb the run row: while the
    # status lived only in memory, any session-level rollback underneath reverted it
    # to "running" and wedged the connection behind the one-running-sync index.
    if run.status == "succeeded" and client is not None:
        report = await embed_pending(session, client)
        run.stats = {
            **(run.stats or {}),
            "embedded": report.embedded,
            "embed_failed_batches": report.failed_batches,
        }
        await session.commit()
    return run


async def _last_checkpoint(session: AsyncSession, connection: Connection) -> dict[str, Any] | None:
    """Latest run WITH a checkpoint, regardless of status — a failed/interrupted
    run carries the partial progress that makes resuming a days-long first crawl
    possible (its mid-crawl commits are the whole point)."""
    result = await session.execute(
        select(SyncRun.checkpoint)
        .where(SyncRun.connection_id == connection.id, SyncRun.checkpoint.is_not(None))
        .order_by(SyncRun.started_at.desc())
        .limit(10)
    )
    for checkpoint in result.scalars():
        if checkpoint:  # skip runs that died before making any progress ({})
            return dict(checkpoint)
    return None


def _page_prefix(source_ref: str) -> str:
    """`wiki://123@4` -> `wiki://123@`, the family of every version of one page."""
    base, sep, _ = source_ref.rpartition("@")
    return f"{base}{sep}" if sep else source_ref


async def _sync_confluence(
    session: AsyncSession, connection: Connection, run: SyncRun
) -> dict[str, Any]:
    config = connection.config or {}
    token = connection_secret(connection)
    if not token:
        raise ValueError("confluence connection requires a credential (stored or secret_env)")
    connector = ConfluenceConnector(
        base_url=connection.base_url,
        email=str(config.get("email", "")),
        api_token=token,
        space_keys=tuple(config.get("space_keys", ())),
        default_acl=tuple(connection.acl_keys or ()),
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
            # A Confluence source_ref embeds the page VERSION (wiki://{id}@{n}), so an
            # edit writes a new row and leaves the previous one behind. Unpruned, that
            # is not merely untidy: superseded text stays retrievable forever under the
            # ACL it had THEN, so restricting a page at the source never takes effect
            # for the version that was public. The git lane already prunes by prefix;
            # this lane never did.
            await session.execute(
                delete(KnowledgeChunk).where(
                    KnowledgeChunk.source_type == document.source_type,
                    KnowledgeChunk.source_ref.startswith(
                        _page_prefix(document.source_ref), autoescape=True
                    ),
                    KnowledgeChunk.source_ref != document.source_ref,
                )
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
    token = connection_secret(connection)
    state = await clone_or_fetch(
        connection.base_url,
        repos_dir / _workdir_name(connection),
        branch=config.get("branch"),
        username=config.get("username") or clone_username(connection.kind),
        token=token,
    )
    # Whole-repo parsing is CPU-bound; keep it off the API event loop or /healthz
    # stalls while a large repo indexes.
    graph = await asyncio.to_thread(
        CodeGraph.build, state.path, repo=connection.name, commit=state.head_sha
    )
    wiki_pages = await generate_module_wikis(graph, client=client)
    acl = list(connection.acl_keys or ["public"])
    current_refs: set[str] = set()
    for page in wiki_pages:
        current_refs.add(page.source_ref)
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
    # Prune: modules deleted at the source must leave retrieval too. This
    # connection's pages share the repo prefix.
    # Module-wiki refs embed the commit (repo://{name}@{sha}/{path}); prune every
    # ref of this repo NOT produced by the current commit.
    prefix = f"repo://{connection.name}@"
    pruned = await session.execute(
        delete(KnowledgeChunk).where(
            KnowledgeChunk.source_type == "code-wiki",
            # autoescape, because `_` is a LIKE wildcard and the connection NAME is
            # user-supplied: a connection called `a_b` would otherwise match — and
            # therefore delete — the indexed chunks of a connection called `axb`.
            KnowledgeChunk.source_ref.startswith(prefix, autoescape=True),
            KnowledgeChunk.source_ref.not_in(current_refs),
        )
    )
    run.checkpoint = {"head_sha": state.head_sha}
    await session.commit()
    return {
        "modules": len(wiki_pages),
        "pruned": int(getattr(pruned, "rowcount", 0) or 0),
        "head_sha": state.head_sha,
    }


async def _sync_jira(session: AsyncSession, connection: Connection, run: SyncRun) -> dict[str, Any]:
    """Optional ledger feed (S9-6). Story points are NOT person-days: the operator
    must state the conversion (`points_to_pd`) — importing raw points as effort
    would silently corrupt calibration."""
    config = connection.config or {}
    token = connection_secret(connection)
    if not token:
        raise ValueError("jira connection requires a credential (stored or secret_env)")
    factor = config.get("points_to_pd")
    if not isinstance(factor, int | float) or factor <= 0:
        raise ValueError(
            "jira connection requires config.points_to_pd (> 0): story points are "
            "not person-days, and the mapping is the operator's claim"
        )
    jql = str(config.get("jql") or "issuetype in (Epic, Story) order by created asc")
    connector = JiraConnector(
        base_url=connection.base_url,
        email=str(config.get("email", "")),
        api_token=token,
    )
    try:
        issues = await connector.pull_issues(jql=jql)
    finally:
        await connector.aclose()

    from estimo_knowledge import LedgerEntryRow

    imported = 0
    for issue in issues:
        if issue.story_points is None:
            continue
        ref = f"jira://{issue.key}"
        row = await session.scalar(select(LedgerEntryRow).where(LedgerEntryRow.origin_ref == ref))
        if row is None:
            row = LedgerEntryRow(origin_ref=ref)
            session.add(row)
        row.brd_ref = issue.parent_key or issue.key
        # A retitled or re-described issue must lose its vector, or the dense leg keeps
        # retrieving it under text it no longer contains — confidently, because a
        # vector carries no visible staleness. Same rule the chunk upsert applies; the
        # embedding writer picks these rows up on its next pass.
        if (row.item_title, row.item_description) != (issue.summary, issue.description):
            row.embedding = None
            row.embedding_model = None
            row.embedding_dim = None
        row.item_title = issue.summary
        row.item_description = issue.description
        row.estimate_single = issue.story_points * float(factor)
        row.method = "jira-story-points"
        imported += 1
    run.checkpoint = {"jql": jql, "issues_seen": len(issues)}
    await session.commit()
    return {"issues": len(issues), "imported": imported}
