"""Analogy cards: the retrieval product the estimator and the UI consume (S3-4).

A card shows a similar past work item with what was estimated then, what actually
happened, and the deviation — the outside view (reference class) evidence that is the
strongest accuracy lever in the founding research (§3.2).
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimo_core import ThreePoint
from estimo_gateway import GatewayClient
from estimo_knowledge.db import LedgerEntryRow
from estimo_knowledge.search import hybrid_ledger_matches


class AnalogyCard(BaseModel):
    model_config = ConfigDict(frozen=True)

    entry_id: uuid.UUID
    rank: int
    # Measured cosine similarity to the query, or None when the dense leg did not
    # run. Never derived from the rank: an ordinal position is not a measurement,
    # and a percentage printed from one would be a fabricated figure on a screen
    # whose whole claim is that its numbers come from somewhere.
    similarity: float | None = None
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


def _card(rank: int, row: LedgerEntryRow, similarity: float | None = None) -> AnalogyCard:
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
        similarity=similarity,
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
    team: str | None = None,
    domain: str | None = None,
) -> list[AnalogyCard]:
    matches = await hybrid_ledger_matches(
        session, text, client=client, limit=limit, team=team, domain=domain
    )
    if not matches:
        return []
    similarity = dict(matches)
    ids = [entry_id for entry_id, _ in matches]
    result = await session.execute(select(LedgerEntryRow).where(LedgerEntryRow.id.in_(ids)))
    by_id = {row.id: row for row in result.scalars()}
    ordered = await _feedback_reorder(session, [i for i in ids if i in by_id])
    return [_card(rank, by_id[i], similarity.get(i)) for rank, i in enumerate(ordered, start=1)]


# Outcome feedback folds into ranking as a bounded nudge (PRINCIPLES #8): retrieval
# similarity stays primary; cumulative outcome weight moves an analog at most
# ±MAX_FEEDBACK_SHIFT positions. Deterministic: base rank breaks ties.
MAX_FEEDBACK_SHIFT = 2.0


async def _feedback_reorder(session: AsyncSession, ids: list[uuid.UUID]) -> list[uuid.UUID]:
    if len(ids) < 2:
        return ids
    from estimo_knowledge.db import AnalogFeedback

    result = await session.execute(
        select(AnalogFeedback.entry_id, func.sum(AnalogFeedback.weight))
        .where(AnalogFeedback.entry_id.in_(ids))
        .group_by(AnalogFeedback.entry_id)
    )
    weights = {entry_id: float(total) for entry_id, total in result}
    if not weights:
        return ids

    def adjusted(pair: tuple[int, uuid.UUID]) -> tuple[float, int]:
        base_rank, entry_id = pair
        shift = max(-MAX_FEEDBACK_SHIFT, min(MAX_FEEDBACK_SHIFT, weights.get(entry_id, 0.0)))
        return (base_rank - shift, base_rank)

    return [entry_id for _, entry_id in sorted(enumerate(ids, start=1), key=adjusted)]
