"""Importer normalization + RRF unit behavior (no database)."""

import uuid

import pytest
from estimo_knowledge import propose_mapping, rrf_merge, to_ledger_entry
from estimo_knowledge.importer import _canonicalize


def row(**overrides: str) -> dict[str, str]:
    base = {"brd_ref": "AUR-1", "item_title": "Test kalemi"}
    base.update(overrides)
    return base


class TestToLedgerEntry:
    def test_three_point_preferred(self) -> None:
        entry = to_ledger_entry(row(est_opt="4", est_likely="6", est_pess="10"))
        assert entry.estimate is not None
        assert entry.estimate.likely == 6.0
        assert entry.estimate_single is None

    def test_single_from_likely_when_range_incomplete(self) -> None:
        entry = to_ledger_entry(row(est_likely="7,5"))
        assert entry.estimate is None
        assert entry.estimate_single == 7.5
        assert entry.point_only is True

    def test_turkish_dates_and_scope(self) -> None:
        entry = to_ledger_entry(row(est_likely="3", est_date="15.06.2025", scope_changed="evet"))
        assert entry.estimated_at is not None
        assert (entry.estimated_at.day, entry.estimated_at.month) == (15, 6)
        assert entry.scope_changed is True

    def test_unrecognized_scope_value_rejected(self) -> None:
        with pytest.raises(ValueError, match="scope_changed"):
            to_ledger_entry(row(est_likely="3", scope_changed="belki"))

    def test_modules_split_on_both_separators(self) -> None:
        entry = to_ledger_entry(row(est_likely="3", modules="billing-core; crm-suite,extra"))
        assert entry.module_tags == ("billing-core", "crm-suite", "extra")

    def test_actual_without_source_rejected(self) -> None:
        with pytest.raises(Exception, match="actual_source"):
            to_ledger_entry(row(est_likely="3", actual_effort="5"))


class TestRrfMerge:
    def test_overlap_wins(self) -> None:
        a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        fused = rrf_merge([[a, b], [b, c]])
        assert fused[0][0] == b  # appears in both rankings

    def test_deterministic_tiebreak(self) -> None:
        a, b = sorted([uuid.uuid4(), uuid.uuid4()], key=str)
        first = rrf_merge([[a], [b]])
        second = rrf_merge([[b], [a]])
        assert [i for i, _ in first] == [i for i, _ in second] == [a, b]


class TestProposeMapping:
    """The wizard's step-2 proposal (S12-6)."""

    def test_turkish_headers_land_on_canonical_fields(self) -> None:
        proposal = propose_mapping(["BRD No", "İş Kalemi", "Gerçekleşen"])
        assert proposal == {
            "BRD No": "brd_ref",
            "İş Kalemi": "item_title",
            "Gerçekleşen": "actual_effort",
        }

    def test_every_header_is_answered_even_when_nothing_matches(self) -> None:
        """An unrecognized column must come back as an explicit `None`, or the wizard
        would drop it silently instead of showing "unmapped"."""
        assert propose_mapping(["serbest not"]) == {"serbest not": None}

    def test_a_field_is_not_claimed_twice(self) -> None:
        """Two columns feeding one field would make which one wins depend on order."""
        proposal = propose_mapping(["efor", "tahmin"])
        assert proposal["efor"] == "est_likely"
        assert proposal["tahmin"] is None


class TestConfirmedMapping:
    """A confirmed mapping is the whole contract — no alias fallback underneath it."""

    def test_only_mapped_columns_are_read(self) -> None:
        raw = {"BRD": "BRD-1", "kalem": "Fatura", "takım": "billing"}
        canonical = _canonicalize(raw, {"BRD": "brd_ref", "kalem": "item_title"})
        assert canonical == {"brd_ref": "BRD-1", "item_title": "Fatura"}
        assert "team" not in canonical, "an unmapped column came back by alias"

    def test_no_mapping_still_uses_aliases(self) -> None:
        canonical = _canonicalize({"takım": "billing"})
        assert canonical == {"team": "billing"}
