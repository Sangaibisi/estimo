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
from collections.abc import Iterable
from dataclasses import dataclass

from estimo_knowledge.db import AnalogFeedback, CalibrationSnapshot, LedgerEntryRow
from estimo_knowledge.importer import normalize_discipline
from sqlalchemy import Date, cast, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from estimo_core import EstimateLine, WorkItem, tr_lower
from estimo_estimate.calibration import transfer_distribution

ROLLING_WINDOW = 20

# Rows the PRODUCT estimated, as opposed to everything that carries an origin. The
# Jira connector writes `jira://{key}` rows with a single number and no band; grading
# the pipeline on those would score it for estimates it never made.
PRODUCT_ORIGIN_PREFIX = "estimate://%"

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


def _normalize_tag(value: str | None) -> str | None:
    """Ledger slice keys are compared, so they are normalized at the boundary."""
    cleaned = tr_lower((value or "").strip())
    return cleaned or None


def _normalize_tags(values: Iterable[str] | None) -> list[str]:
    seen: list[str] = []
    for value in values or ():
        tag = _normalize_tag(value)
        if tag and tag not in seen:
            seen.append(tag)
    return seen


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
    team: str | None = None,
    domain_tags: list[str] | None = None,
    discipline: str | None = None,
) -> LedgerEntryRow:
    """Upsert the ledger row for this line, then re-derive feedback + snapshot.

    Idempotent per (estimate, work item): re-recording revises the actual and
    REPLACES the feedback derived from the previous recording — including
    withdrawing it entirely when the revision flips to scope_changed (an excluded
    actual must stop influencing ranking) or when a rebuilt line cites different
    analogs (stale weights on dropped analogs would outlive their evidence).
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
    # Attribution comes from whoever closes the loop, falling back to the work item.
    # The pipeline cannot supply it: a BRD says what to build, never which team will
    # build it, so `WorkItem` is constructed without a team and every product-written
    # row landed with team = NULL. Slicing calibration by team needs this column, and
    # a NULL written today is unrecoverable — nobody reconstructs it a year later.
    # Normalized so "Billing" and "billing" are one slice, not two (Turkish-aware:
    # str.lower() maps "I" to "i", not "ı").
    row.domain_tags = _normalize_tags(domain_tags if domain_tags is not None else item.domain_tags)
    row.team = _normalize_tag(team if team is not None else item.team)
    # S13-3 slice key. Same boundary rule as team/domain — normalized, aliases
    # folded, anything unrecognized raises before it can mint a third discipline.
    row.discipline = normalize_discipline(discipline)
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

    # Withdraw feedback from any previous recording of this line before
    # (conditionally) re-deriving it — see the docstring.
    await session.execute(delete(AnalogFeedback).where(AnalogFeedback.origin_ref == ref))
    if not scope_changed:
        await _apply_feedback(session, ref, actual_effort, line)
    # Snapshot unconditionally: a revision that EXCLUDES a row moves the
    # calibration state too, and the series must register it.
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


@dataclass(frozen=True)
class RollingCoverage:
    """A coverage rate that cannot be read without its sample count.

    Coverage at ±5% needs ~100 points; at n=2 the value is 0.0 or 0.5 or 1.0 and means
    nothing. Returning a bare float made it too easy for a caller to render the number
    alone — so the count travels with it, and the caller decides what is showable.
    """

    coverage: float
    samples: int


async def rolling_coverage(
    session: AsyncSession, *, window: int = ROLLING_WINDOW
) -> RollingCoverage | None:
    """Empirical coverage of the last `window` completed product-origin rows.

    The drift signal (web-verified design): a sustained gap between this and the
    nominal band means the process changed and history stopped transferring.

    `origin_ref LIKE 'estimate://%'` and NOT merely `IS NOT NULL`: the Jira connector
    writes rows under `jira://…`, and those carry a single number rather than a band,
    so counting them here would grade the pipeline on estimates it never made.
    """
    result = await session.execute(
        select(
            LedgerEntryRow.est_optimistic,
            LedgerEntryRow.est_pessimistic,
            LedgerEntryRow.actual_effort,
        )
        .where(
            LedgerEntryRow.origin_ref.like(PRODUCT_ORIGIN_PREFIX),
            LedgerEntryRow.actual_effort.is_not(None),
            LedgerEntryRow.scope_changed.is_(False),
            LedgerEntryRow.est_optimistic.is_not(None),
            LedgerEntryRow.est_pessimistic.is_not(None),
        )
        # "The last N" has to mean the last N JOBS, not the last N rows written. A seed
        # import commits every row in one transaction, so created_at ties across the
        # whole file and the window would be an arbitrary subset.
        #
        # COALESCE, not NULLS LAST: `completed_at` is optional on the product's own
        # write path (the web client does not send it at all), so ordering dated rows
        # ahead of undated ones parked the window on whatever imported history happened
        # to carry dates and the product's own recent work could never enter it — the
        # drift signal would be pinned to the past forever. A row that never said when
        # it finished is dated by when it was recorded, which is the best fact there is.
        .order_by(
            func.coalesce(
                LedgerEntryRow.completed_at, cast(LedgerEntryRow.created_at, Date)
            ).desc(),
            LedgerEntryRow.created_at.desc(),
            LedgerEntryRow.id,
        )
        .limit(window)
    )
    rows = result.all()
    if not rows:
        return None
    hits = sum(1 for opt, pess, actual in rows if float(opt) <= float(actual) <= float(pess))
    return RollingCoverage(coverage=hits / len(rows), samples=len(rows))


async def snapshot_calibration(
    session: AsyncSession, *, trigger: str, nominal: float = 0.8
) -> CalibrationSnapshot:
    distribution = await transfer_distribution(session)
    rolling = await rolling_coverage(session)
    snapshot = CalibrationSnapshot(
        samples=distribution.samples,
        prior_based=distribution.prior_based,
        q10=distribution.q10,
        q50=distribution.q50,
        q90=distribution.q90,
        nominal=nominal,
        rolling_coverage=(rolling.coverage if rolling else None),
        rolling_samples=(rolling.samples if rolling else None),
        trigger=trigger,
    )
    session.add(snapshot)
    await session.flush()
    return snapshot
