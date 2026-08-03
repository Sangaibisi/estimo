"""Calibration loop (S8-1/S8-2): actuals close the loop back into the ledger.

Recording an actual for an estimated line does three things in one transaction:

1. **Ledger upsert** — the line becomes a first-class `ledger_entries` row with
   `origin_ref = estimate://{estimate_id}/{work_item_id}`, so future analog retrieval
   and calibration learn from the product's own history exactly like imported history.
2. **Analog feedback** (PRINCIPLES #8) — every `ledger://` analog that backed the line
   receives an outcome weight: covered actuals reward the analogs, misses demote them
   proportionally to the log-error. `find_analogs` folds cumulative weight into rank.
3. **Calibration snapshot** — the transfer-error quantiles and a rolling empirical
   coverage are stored for the drift dashboard. Design choice (web-verified): at this
   ledger scale (30–500 rows) event-driven FULL recompute per actual is simpler and at
   least as good as online/streaming conformal updates; drift is surfaced via rolling
   coverage rather than chased with per-step adaptation.

Scope-changed actuals are stored (honesty) but excluded from feedback and calibration,
matching `transfer_distribution`'s exclusion rule.
"""

from __future__ import annotations

import datetime as dt
import math
import uuid

from estimo_knowledge.db import AnalogFeedback, CalibrationSnapshot, LedgerEntryRow
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from estimo_core import EstimateLine, WorkItem
from estimo_estimate.calibration import transfer_distribution

ROLLING_WINDOW = 20

# Feedback weights: explainable constants, clamped so no single outcome can bury an
# analog for good (cumulative weight is clamped again at ranking time).
_COVERED_WEIGHT = 0.5
_MISS_WEIGHT_CAP = 1.0


def origin_ref(estimate_id: uuid.UUID, work_item_id: str) -> str:
    return f"estimate://{estimate_id}/{work_item_id}"


def _feedback_weight(actual: float, line: EstimateLine) -> tuple[float, str]:
    band = line.range
    if band.optimistic <= actual <= band.pessimistic:
        return _COVERED_WEIGHT, "band-covered-actual"
    likely = band.likely if band.likely > 0 else 0.01
    miss = min(_MISS_WEIGHT_CAP, abs(math.log(max(actual, 0.01) / likely)))
    return -miss, "band-missed-actual"


async def record_actual(
    session: AsyncSession,
    *,
    estimate_id: uuid.UUID,
    brd_ref: str,
    brd_title: str,
    item: WorkItem,
    line: EstimateLine,
    actual_effort: float,
    actual_source: str,
    completed_at: dt.date | None = None,
    scope_changed: bool = False,
    estimated_at: dt.date | None = None,
) -> LedgerEntryRow:
    """Upsert the ledger row for this line, then apply feedback + snapshot.

    Idempotent per (estimate, work item): re-recording revises the actual and the
    feedback weights instead of stacking duplicates.
    """
    ref = origin_ref(estimate_id, item.id)
    row = await session.scalar(select(LedgerEntryRow).where(LedgerEntryRow.origin_ref == ref))
    if row is None:
        row = LedgerEntryRow(origin_ref=ref)
        session.add(row)
    row.brd_ref = brd_ref
    row.brd_title = brd_title
    row.item_title = item.title
    row.item_description = item.description
    row.module_tags = list(item.module_tags)
    row.domain_tags = list(item.domain_tags)
    row.team = item.team
    row.est_optimistic = line.range.optimistic
    row.est_likely = line.range.likely
    row.est_pessimistic = line.range.pessimistic
    row.estimated_at = estimated_at
    row.method = "estimo-boe"
    row.actual_effort = actual_effort
    row.actual_source = actual_source
    row.completed_at = completed_at
    row.scope_changed = scope_changed
    await session.flush()

    if not scope_changed:
        await _apply_feedback(session, ref, actual_effort, line)
        await snapshot_calibration(session, trigger="actual-recorded")
    return row


async def _apply_feedback(
    session: AsyncSession, ref: str, actual: float, line: EstimateLine
) -> int:
    weight, reason = _feedback_weight(actual, line)
    applied = 0
    for evidence in line.evidence:
        scheme, _, rest = evidence.uri.partition("://")
        if scheme != "ledger":
            continue
        try:
            entry_id = uuid.UUID(rest)
        except ValueError:
            continue
        statement = (
            pg_insert(AnalogFeedback)
            .values(
                id=uuid.uuid4(),
                entry_id=entry_id,
                origin_ref=ref,
                weight=weight,
                reason=reason,
            )
            .on_conflict_do_update(
                index_elements=[AnalogFeedback.entry_id, AnalogFeedback.origin_ref],
                set_={"weight": weight, "reason": reason},
            )
        )
        await session.execute(statement)
        applied += 1
    return applied


async def rolling_coverage(session: AsyncSession, *, window: int = ROLLING_WINDOW) -> float | None:
    """Empirical coverage of the last `window` completed product-origin rows.

    The drift signal (web-verified design): a sustained gap between this and the
    nominal band means the process changed and history stopped transferring. With few
    samples the value is noisy (coverage at ±5% needs ~100 points) — callers must
    always show the sample count next to it.
    """
    result = await session.execute(
        select(
            LedgerEntryRow.est_optimistic,
            LedgerEntryRow.est_pessimistic,
            LedgerEntryRow.actual_effort,
        )
        .where(
            LedgerEntryRow.origin_ref.is_not(None),
            LedgerEntryRow.actual_effort.is_not(None),
            LedgerEntryRow.scope_changed.is_(False),
            LedgerEntryRow.est_optimistic.is_not(None),
            LedgerEntryRow.est_pessimistic.is_not(None),
        )
        .order_by(LedgerEntryRow.created_at.desc())
        .limit(window)
    )
    rows = result.all()
    if not rows:
        return None
    hits = sum(1 for opt, pess, actual in rows if float(opt) <= float(actual) <= float(pess))
    return hits / len(rows)


async def snapshot_calibration(
    session: AsyncSession, *, trigger: str, nominal: float = 0.8
) -> CalibrationSnapshot:
    distribution = await transfer_distribution(session)
    snapshot = CalibrationSnapshot(
        samples=distribution.samples,
        prior_based=distribution.prior_based,
        q10=distribution.q10,
        q50=distribution.q50,
        q90=distribution.q90,
        nominal=nominal,
        rolling_coverage=await rolling_coverage(session),
        trigger=trigger,
    )
    session.add(snapshot)
    await session.flush()
    return snapshot
