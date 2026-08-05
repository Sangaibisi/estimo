"""Range calibration from the ledger's own error history (S6-3).

The empirical deviation distribution (actual / likely) supplies the band multipliers —
the same recipe as Jørgensen's historical-error prediction intervals, and the reason
experts' uncalibrated 90% intervals only hit 60–70% (RESEARCH §3.2). Cold-start priors
apply below a minimum sample size and are ALWAYS labeled as prior-based.
"""

from __future__ import annotations

from dataclasses import dataclass

from estimo_knowledge import LedgerEntryRow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

MIN_SAMPLES = 8

# Cold-start priors: research-derived defaults (RESEARCH §3/§4 — optimistic bias and
# right-skewed overruns), used verbatim until the tenant's own history takes over.
PRIOR_Q10 = 0.7
PRIOR_Q50 = 1.0
PRIOR_Q90 = 1.6

# Expert recall is optimism-prone; it participates with half weight (LEDGER-SCHEMA).
_RECALL_WEIGHT = 0.5


@dataclass(frozen=True)
class ErrorDistribution:
    q10: float
    q50: float
    q90: float
    samples: int
    prior_based: bool

    @classmethod
    def prior(cls, samples: int = 0) -> ErrorDistribution:
        return cls(q10=PRIOR_Q10, q50=PRIOR_Q50, q90=PRIOR_Q90, samples=samples, prior_based=True)


def _weighted_quantile(pairs: list[tuple[float, float]], quantile: float) -> float:
    ordered = sorted(pairs)
    total = sum(weight for _, weight in ordered)
    target = quantile * total
    cumulative = 0.0
    for value, weight in ordered:
        cumulative += weight
        if cumulative >= target:
            return value
    return ordered[-1][0]


async def transfer_distribution(
    session: AsyncSession, *, analog_limit: int = 6
) -> ErrorDistribution:
    """Conformal-style calibration of ANALOG-BASED bands.

    The error that matters for an analog-grounded band is the transfer error —
    held-out actual / analog median — not the entry's own estimate deviation
    (measured: using the latter yields 7% interval coverage on the seed set). Ratios
    are computed leave-one-out over the ledger itself, so the quantiles self-calibrate
    to how transferable this tenant's history actually is: a diverse ledger honestly
    produces wide bands.
    """
    from estimo_knowledge import find_analogs

    result = await session.execute(
        select(LedgerEntryRow).where(
            LedgerEntryRow.actual_effort.is_not(None),
            LedgerEntryRow.scope_changed.is_(False),
        )
    )
    pairs: list[tuple[float, float]] = []
    for row in result.scalars():
        actual = float(row.actual_effort)  # type: ignore[arg-type]
        query = f"{row.item_title} {row.item_description or ''}"
        analogs = [
            card
            for card in await find_analogs(session, query, limit=analog_limit)
            if card.entry_id != row.id
        ]
        values: list[float] = []
        for card in analogs:
            if card.actual_effort is not None and not card.scope_changed:
                values.append(card.actual_effort)
            elif card.estimate is not None:
                values.append(card.estimate.likely)
            elif card.estimate_single is not None:
                values.append(card.estimate_single)
        if not values:
            continue
        values.sort()
        mid = len(values) // 2
        median = values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2
        if median <= 0:
            continue
        weight = _RECALL_WEIGHT if row.actual_source == "expert-recall" else 1.0
        pairs.append((actual / median, weight))

    if len(pairs) < MIN_SAMPLES:
        return ErrorDistribution.prior(samples=len(pairs))
    return ErrorDistribution(
        q10=_weighted_quantile(pairs, 0.10),
        q50=_weighted_quantile(pairs, 0.50),
        q90=_weighted_quantile(pairs, 0.90),
        samples=len(pairs),
        prior_based=False,
    )


async def error_distribution(session: AsyncSession) -> ErrorDistribution:
    """Deviation quantiles over completed, scope-stable ledger rows."""
    result = await session.execute(
        select(
            LedgerEntryRow.est_likely,
            LedgerEntryRow.estimate_single,
            LedgerEntryRow.actual_effort,
            LedgerEntryRow.actual_source,
        ).where(
            LedgerEntryRow.actual_effort.is_not(None),
            LedgerEntryRow.scope_changed.is_(False),
        )
    )
    pairs: list[tuple[float, float]] = []
    for est_likely, est_single, actual, source in result:
        likely = (
            float(est_likely)
            if est_likely is not None
            else (float(est_single) if est_single is not None else None)
        )
        if not likely or actual is None:
            continue
        weight = _RECALL_WEIGHT if source == "expert-recall" else 1.0
        pairs.append((float(actual) / likely, weight))

    if len(pairs) < MIN_SAMPLES:
        return ErrorDistribution.prior(samples=len(pairs))
    return ErrorDistribution(
        q10=_weighted_quantile(pairs, 0.10),
        q50=_weighted_quantile(pairs, 0.50),
        q90=_weighted_quantile(pairs, 0.90),
        samples=len(pairs),
        prior_based=False,
    )


@dataclass(frozen=True)
class DisciplineHistory:
    """What the ledger knows about the FE/BE split (S13-3).

    `rows` are the completed, scope-stable rows that CARRY a discipline —
    (module_tags, discipline, effort) triples, effort preferring the actual. Loaded
    once per estimate run; the per-module ratio is then pure arithmetic per item.
    `counts` feed the calibrated/uncalibrated badge: a discipline slice below
    MIN_SAMPLES renders as "model-proposed, uncalibrated" (S12-7 honest silence).
    """

    rows: tuple[tuple[frozenset[str], str, float], ...]
    counts: dict[str, int]

    def calibrated(self, discipline: str) -> bool:
        return self.counts.get(discipline, 0) >= MIN_SAMPLES


async def discipline_history(session: AsyncSession) -> DisciplineHistory:
    result = await session.execute(
        select(
            LedgerEntryRow.module_tags,
            LedgerEntryRow.discipline,
            LedgerEntryRow.actual_effort,
            LedgerEntryRow.est_likely,
            LedgerEntryRow.estimate_single,
        ).where(
            LedgerEntryRow.discipline.is_not(None),
            LedgerEntryRow.actual_effort.is_not(None),
            LedgerEntryRow.scope_changed.is_(False),
        )
    )
    rows: list[tuple[frozenset[str], str, float]] = []
    counts: dict[str, int] = {}
    for modules, discipline, actual, likely, single in result:
        effort = float(actual if actual is not None else likely or single or 0)
        if effort <= 0:
            continue
        rows.append((frozenset(modules or []), str(discipline), effort))
        counts[str(discipline)] = counts.get(str(discipline), 0) + 1
    return DisciplineHistory(rows=tuple(rows), counts=counts)


def historical_ratio(
    history: DisciplineHistory, module_tags: tuple[str, ...] | list[str]
) -> dict[str, float] | None:
    """The tenant's own FE/BE effort ratio, per module first, globally second.

    None unless BOTH disciplines have measured effort in the chosen scope — a ratio
    computed from one side would claim the other side is free, which is exactly the
    kind of confident zero this product refuses to print (PRINCIPLES #6).
    """
    wanted = set(module_tags)
    scoped = [row for row in history.rows if wanted and row[0] & wanted]
    for pool in (scoped, list(history.rows)):
        sums: dict[str, float] = {}
        for _, discipline, effort in pool:
            sums[discipline] = sums.get(discipline, 0.0) + effort
        if len(sums) >= 2 and all(value > 0 for value in sums.values()):
            total = sum(sums.values())
            return {discipline: value / total for discipline, value in sums.items()}
    return None
