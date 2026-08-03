"""Three-point band construction from analogs + calibrated deviation quantiles (S6-1/2/3).

The likely value comes from the analogs' OUTCOMES (actuals preferred over given
estimates — the outside view); the band width comes from the tenant's deviation
distribution. Small items get overhead floors instead of scaled bands (PRINCIPLES #10:
the ≤5 CFP correlation collapse). No verbalized confidence anywhere (PRINCIPLES #6).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from estimo_knowledge import AnalogyCard

from estimo_core import Confidence, ThreePoint
from estimo_estimate.calibration import ErrorDistribution

SMALL_ITEM_THRESHOLD = 2.0
SMALL_ITEM_MIN_SPREAD = 1.0
MIN_OPTIMISTIC = 0.25


@dataclass(frozen=True)
class BandResult:
    range: ThreePoint
    confidence: Confidence
    basis: str


def _analog_value(card: AnalogyCard) -> float | None:
    if card.actual_effort is not None and not card.scope_changed:
        return card.actual_effort
    if card.estimate is not None:
        return card.estimate.likely
    return card.estimate_single


def band_from_analogs(
    analogs: list[AnalogyCard], distribution: ErrorDistribution
) -> BandResult | None:
    """None when no usable analogs exist — the caller must flag, never invent."""
    values = [v for card in analogs if (v := _analog_value(card)) is not None]
    if not values:
        return None
    median = statistics.median(values)
    # All three points derive from the MEDIAN: quantiles are ratios of actual to the
    # analog median, so multiplying edges off the (already q50-scaled) likely would
    # apply q50 twice and break the conformal coverage guarantee.
    likely = round(median * distribution.q50, 1)
    optimistic = max(round(median * distribution.q10, 1), MIN_OPTIMISTIC)
    pessimistic = round(median * distribution.q90, 1)

    if likely < SMALL_ITEM_THRESHOLD:
        # Overhead floor: tiny items are dominated by fixed costs, not size.
        pessimistic = max(pessimistic, likely + SMALL_ITEM_MIN_SPREAD)

    optimistic = min(optimistic, likely)
    pessimistic = max(pessimistic, likely)

    with_actuals = sum(
        1 for card in analogs if card.actual_effort is not None and not card.scope_changed
    )
    if with_actuals >= 2 and not distribution.prior_based:
        confidence = Confidence.HIGH
    elif with_actuals >= 1:
        confidence = Confidence.MEDIUM
    else:
        confidence = Confidence.LOW

    basis_bits = [
        f"{len(values)} analog (median {median:.1f} pd)",
        f"deviation quantiles q10={distribution.q10:.2f} q50={distribution.q50:.2f} "
        f"q90={distribution.q90:.2f}"
        + (
            " [cold-start prior]"
            if distribution.prior_based
            else f" [{distribution.samples} samples]"
        ),
    ]
    return BandResult(
        range=ThreePoint(optimistic=optimistic, likely=likely, pessimistic=pessimistic),
        confidence=confidence,
        basis="; ".join(basis_bits),
    )
