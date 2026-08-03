"""Analogy cards: the retrieval product the estimator and the UI consume (S3-4).

A card shows a similar past work item with what was estimated then, what actually
happened, and the deviation — the outside view (reference class) evidence that is the
strongest accuracy lever in the founding research (§3.2).
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimo_core import ThreePoint
from estimo_gateway import GatewayClient
from estimo_knowledge.db import LedgerEntryRow
from estimo_knowledge.search import hybrid_ledger_ids


class AnalogyCard(BaseModel):
    model_config = ConfigDict(frozen=True)

    entry_id: uuid.UUID
    rank: int
    brd_ref: str
    item_title: str
    module_tags: tuple[str, ...] = ()
    domain_tags: tuple[str, ...] = ()
    team: str | None = None
    method: str | None = None
    estimate: ThreePoint | None = None
    estimate_single: float | None = None
    actual_effort: float | None = None
    actual_source: Literal["timesheet", "project-report", "expert-recall"] | None = None
    scope_changed: bool = False
    deviation: float | None = None


def _card(rank: int, row: LedgerEntryRow) -> AnalogyCard:
    estimate: ThreePoint | None = None
    if row.est_likely is not None and row.est_optimistic is not None:
        estimate = ThreePoint(
            optimistic=float(row.est_optimistic),
            likely=float(row.est_likely),
            pessimistic=float(row.est_pessimistic or row.est_likely),
        )
    single = float(row.estimate_single) if row.estimate_single is not None else None
    likely = estimate.likely if estimate else single
    actual = float(row.actual_effort) if row.actual_effort is not None else None
    deviation = (actual / likely) if (actual is not None and likely) else None
    return AnalogyCard(
        entry_id=row.id,
        rank=rank,
        brd_ref=row.brd_ref,
        item_title=row.item_title,
        module_tags=tuple(row.module_tags or ()),
        domain_tags=tuple(row.domain_tags or ()),
        team=row.team,
        method=row.method,
        estimate=estimate,
        estimate_single=single,
        actual_effort=actual,
        actual_source=row.actual_source,
        scope_changed=row.scope_changed,
        deviation=deviation,
    )


async def find_analogs(
    session: AsyncSession,
    text: str,
    *,
    client: GatewayClient | None = None,
    limit: int = 5,
) -> list[AnalogyCard]:
    ids = await hybrid_ledger_ids(session, text, client=client, limit=limit)
    if not ids:
        return []
    result = await session.execute(select(LedgerEntryRow).where(LedgerEntryRow.id.in_(ids)))
    by_id = {row.id: row for row in result.scalars()}
    return [_card(rank, by_id[i]) for rank, i in enumerate(ids, start=1) if i in by_id]
