"""Domain-model behavior: the structurally-enforced product laws."""

import pytest
from pydantic import ValidationError

from estimo_core import (
    AssumptionRisk,
    BoeDocument,
    ConeStage,
    Confidence,
    EstimateLine,
    EvidenceKind,
    EvidenceRef,
    LedgerEntry,
    Requirement,
    ThreePoint,
)

EVIDENCE = EvidenceRef.from_uri("repo://billing-core@ab12cd3/src/Invoice.java#L10-L42")


def make_line(**overrides: object) -> EstimateLine:
    base: dict[str, object] = {
        "work_item_id": "WI-1",
        "range": ThreePoint(optimistic=2, likely=4, pessimistic=9),
        "confidence": Confidence.MEDIUM,
        "evidence": (EVIDENCE,),
    }
    base.update(overrides)
    return EstimateLine.model_validate(base)


class TestThreePoint:
    def test_ordering_enforced(self) -> None:
        with pytest.raises(ValidationError, match="optimistic <= likely <= pessimistic"):
            ThreePoint(optimistic=5, likely=4, pessimistic=9)

    def test_addition(self) -> None:
        total = ThreePoint(optimistic=1, likely=2, pessimistic=3) + ThreePoint(
            optimistic=2, likely=3, pessimistic=4
        )
        assert (total.optimistic, total.likely, total.pessimistic) == (3.0, 5.0, 7.0)


class TestEvidenceRef:
    def test_scheme_kind_inferred(self) -> None:
        assert EVIDENCE.kind is EvidenceKind.CODE

    def test_scheme_kind_mismatch_rejected(self) -> None:
        with pytest.raises(ValidationError, match="implies kind"):
            EvidenceRef(uri="wiki://12345@7", kind=EvidenceKind.CODE)

    def test_unknown_scheme_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown evidence scheme"):
            EvidenceRef.from_uri("ftp://somewhere")


class TestEstimateLine:
    def test_no_line_without_evidence(self) -> None:
        """PRINCIPLES #2 is a type-level guarantee."""
        with pytest.raises(ValidationError):
            make_line(evidence=())

    def test_registers_reject_mistyped_entries(self) -> None:
        risk = AssumptionRisk(kind="risk", text="Legacy adapter unknown", contingency_pd=3)
        with pytest.raises(ValidationError, match="assumption"):
            make_line(assumptions=(risk,))


class TestBoeDocument:
    def test_total_sums_ranges(self) -> None:
        boe = BoeDocument(
            brd_ref="BRD-AUR-26-01",
            title="Kampanya Bazlı Cihaz Taksitlendirme",
            cone_stage=ConeStage.CONCEPT,
            lines=(
                make_line(),
                make_line(range=ThreePoint(optimistic=1, likely=2, pessimistic=4)),
            ),
        )
        assert boe.total.likely == 6.0
        assert boe.locale == "tr"

    def test_turkish_content_roundtrip(self) -> None:
        req = Requirement(id="REQ-G-04", text="Kurumsal müşteriler için farklı koşullar")
        again = Requirement.model_validate_json(req.model_dump_json())
        assert again.text == "Kurumsal müşteriler için farklı koşullar"


class TestLedgerEntry:
    def test_exactly_one_estimate_shape(self) -> None:
        with pytest.raises(ValidationError, match="exactly one"):
            LedgerEntry(brd_ref="B-1", item_title="x")
        with pytest.raises(ValidationError, match="exactly one"):
            LedgerEntry(
                brd_ref="B-1",
                item_title="x",
                estimate=ThreePoint(optimistic=1, likely=2, pessimistic=3),
                estimate_single=2,
            )

    def test_actual_requires_source(self) -> None:
        with pytest.raises(ValidationError, match="actual_source"):
            LedgerEntry(brd_ref="B-1", item_title="x", estimate_single=5, actual_effort=7)

    def test_point_only_and_deviation(self) -> None:
        row = LedgerEntry(
            brd_ref="B-1",
            item_title="x",
            estimate_single=5,
            actual_effort=7,
            actual_source="timesheet",
        )
        assert row.point_only is True
        assert row.deviation == pytest.approx(1.4)
