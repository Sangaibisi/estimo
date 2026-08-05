"""Persisted CodeGraphs (S13-2): what a git sync builds, the estimator can load.

Before this module the graph existed for the lifetime of one `_sync_git` call —
built, used for wiki generation, discarded — while the one consumer that wanted it
(`estimate_state`'s impact evidence) never received a graph in the deployed path.
One row per (tenant, connection); a re-sync replaces the payload in place.
"""

from __future__ import annotations

import uuid
from typing import Any

from estimo_code import CodeGraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimo_connectors.db import CodeGraphRow


async def upsert_code_graph(
    session: AsyncSession, connection_id: uuid.UUID, name: str, graph: CodeGraph
) -> dict[str, Any]:
    """Store `graph` as the connection's current graph. Returns size stats.

    Does NOT commit: `_sync_git` owns the transaction and commits the graph together
    with its checkpoint, so a crash between the two cannot record a sync whose graph
    is missing (or the reverse).
    """
    stats = {
        "files": len(graph.files),
        "symbols": sum(len(f.symbols) for f in graph.files),
        "modules": len(set(graph.module_of.values())),
    }
    row = await session.scalar(
        select(CodeGraphRow).where(CodeGraphRow.connection_id == connection_id)
    )
    if row is None:
        row = CodeGraphRow(
            connection_id=connection_id,
            repo=name,
            commit=graph.commit,
            payload=graph.to_payload(),
            stats=stats,
        )
        session.add(row)
    else:
        row.repo = name
        row.commit = graph.commit
        row.payload = graph.to_payload()
        row.stats = stats
    return stats


async def load_code_graphs(session: AsyncSession) -> list[CodeGraph]:
    """Every persisted graph the session can see (RLS scopes this to the tenant).

    A payload that no longer deserializes — a future schema change, a manually
    edited row — is skipped rather than failing the estimate: a broken graph must
    degrade to "no code evidence", not to "no BoE".
    """
    graphs: list[CodeGraph] = []
    rows = await session.execute(select(CodeGraphRow).order_by(CodeGraphRow.repo))
    for row in rows.scalars():
        try:
            graphs.append(CodeGraph.from_payload(row.payload))
        except (KeyError, TypeError, ValueError):
            continue
    return graphs
