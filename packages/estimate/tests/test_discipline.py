"""The FE/BE discipline dimension (S13-3): split derivation + honest silence.

The split's precedence is worker-proposal > tenant historical ratio > NOTHING; the
badge logic (calibrated only above MIN_SAMPLES per slice) rides on DisciplineHistory.
Pure unit tests here; the seeded end-to-end path is exercised in test_estimate.py.
"""

from __future__ import annotations

import pytest
from estimo_estimate.calibration import (
    MIN_SAMPLES,
    DisciplineHistory,
    historical_ratio,
)
from estimo_estimate.estimator import _discipline_split

from estimo_core import Confidence, DisciplineShare, ImpactAnalysis, ThreePoint

BAND = ThreePoint(optimistic=4.0, likely=8.0, pessimistic=16.0)

_EMPTY = DisciplineHistory(rows=(), counts={})


def _analysis(shares: list[tuple[str, float]]) -> ImpactAnalysis:
    return ImpactAnalysis(
        work_item_id="WI-01",
        composition=tuple(DisciplineShare(discipline=d, share=s) for d, s in shares),
        source="agentic",
    )


class TestSplit:
    def test_worker_composition_scales_the_final_band(self) -> None:
        parts = _discipline_split(
            BAND, _analysis([("frontend", 0.25), ("backend", 0.75)]), _EMPTY, ()
        )
        by = {part.discipline: part for part in parts}
        assert by["frontend"].range == ThreePoint(optimistic=1.0, likely=2.0, pessimistic=4.0)
        assert by["backend"].range == ThreePoint(optimistic=3.0, likely=6.0, pessimistic=12.0)
        assert all(part.basis == "model-proposed" for part in parts)
        # No per-discipline history yet: the badge stays on.
        assert all(not part.calibrated for part in parts)

    def test_historical_ratio_is_the_naive_baseline(self) -> None:
        history = DisciplineHistory(
            rows=(
                (frozenset({"billing-core"}), "frontend", 10.0),
                (frozenset({"billing-core"}), "backend", 30.0),
            ),
            counts={"frontend": 1, "backend": 1},
        )
        parts = _discipline_split(BAND, None, history, ("billing-core",))
        by = {part.discipline: part for part in parts}
        assert by["frontend"].range.likely == 2.0  # 8 × 0.25
        assert by["backend"].range.likely == 6.0
        assert all(part.basis == "historical-ratio" for part in parts)

    def test_no_basis_means_no_split(self) -> None:
        assert _discipline_split(BAND, None, _EMPTY, ("billing-core",)) == ()
        # An analysis WITHOUT a composition falls through to history — still nothing.
        assert (
            _discipline_split(
                BAND,
                ImpactAnalysis(work_item_id="WI-01", source="agentic"),
                _EMPTY,
                (),
            )
            == ()
        )

    def test_calibrated_flag_needs_min_samples(self) -> None:
        history = DisciplineHistory(
            rows=(),
            counts={"frontend": MIN_SAMPLES, "backend": MIN_SAMPLES - 1},
        )
        parts = _discipline_split(
            BAND, _analysis([("frontend", 0.5), ("backend", 0.5)]), history, ()
        )
        by = {part.discipline: part for part in parts}
        assert by["frontend"].calibrated
        assert not by["backend"].calibrated


class TestHistoricalRatio:
    def test_module_scope_wins_over_global(self) -> None:
        history = DisciplineHistory(
            rows=(
                (frozenset({"billing-core"}), "frontend", 10.0),
                (frozenset({"billing-core"}), "backend", 10.0),
                (frozenset({"dealer-portal"}), "frontend", 90.0),
                (frozenset({"dealer-portal"}), "backend", 10.0),
            ),
            counts={},
        )
        scoped = historical_ratio(history, ("billing-core",))
        assert scoped == {"frontend": 0.5, "backend": 0.5}
        portal = historical_ratio(history, ("dealer-portal",))
        assert portal is not None and portal["frontend"] == pytest.approx(0.9)

    def test_one_sided_history_yields_nothing(self) -> None:
        # A ratio from one discipline would claim the other is free (PRINCIPLES #6).
        history = DisciplineHistory(
            rows=((frozenset({"billing-core"}), "backend", 30.0),), counts={}
        )
        assert historical_ratio(history, ("billing-core",)) is None
        assert historical_ratio(history, ()) is None

    def test_unknown_module_falls_back_to_global(self) -> None:
        history = DisciplineHistory(
            rows=(
                (frozenset({"billing-core"}), "frontend", 20.0),
                (frozenset({"crm-suite"}), "backend", 60.0),
            ),
            counts={},
        )
        ratio = historical_ratio(history, ("no-such-module",))
        assert ratio is not None
        assert ratio["backend"] == pytest.approx(0.75)


class TestDocumentTotals:
    def test_discipline_totals_roll_up_only_split_lines(self) -> None:
        from estimo_core import BoeDocument, ConeStage, DisciplineRange, EstimateLine, EvidenceRef

        def line(item_id: str, disciplines: tuple[DisciplineRange, ...]) -> EstimateLine:
            return EstimateLine(
                work_item_id=item_id,
                range=BAND,
                confidence=Confidence.LOW,
                evidence=(EvidenceRef.from_uri("note://x"),),
                disciplines=disciplines,
            )

        split = (
            DisciplineRange(
                discipline="frontend",
                range=ThreePoint(optimistic=1, likely=2, pessimistic=4),
                basis="model-proposed",
            ),
            DisciplineRange(
                discipline="backend",
                range=ThreePoint(optimistic=3, likely=6, pessimistic=12),
                basis="model-proposed",
            ),
        )
        boe = BoeDocument(
            brd_ref="BRD-X",
            title="t",
            cone_stage=ConeStage.CONCEPT,
            lines=(line("WI-1", split), line("WI-2", ())),
        )
        totals = boe.discipline_totals
        assert totals["frontend"].likely == 2
        assert totals["backend"].pessimistic == 12
        # WI-2 contributed to neither bucket — the split may honestly under-cover.
        assert totals["backend"].likely + totals["frontend"].likely < boe.total.likely
