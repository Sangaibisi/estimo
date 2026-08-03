"""Parse golden eval (S2-5): every planted feature in the fixture manifest must be found.

This suite runs in CI on every PR; the fixtures' planted anchors/ambiguities are the
ground truth (fixtures/brd/manifest.json, maintained by the generator).
"""

import json
from pathlib import Path

import pytest
from estimo_parse import GATE_THRESHOLD, parse_brd
from estimo_parse.models import ParsedBrd

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "brd"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
BY_FILE = {entry["file"]: entry for entry in MANIFEST["brds"]}


@pytest.fixture(scope="module")
def parsed() -> dict[str, ParsedBrd]:
    return {name: parse_brd(FIXTURES / name) for name in BY_FILE}


def test_all_planted_anchors_detected(parsed: dict[str, ParsedBrd]) -> None:
    """Exit-gate requirement: anchor detection catches every planted anchor."""
    for name, entry in BY_FILE.items():
        doc = parsed[name]
        for planted in entry["planted_anchors"]:
            hits = [a for a in doc.doc_anchors if a.type == planted["type"]]
            assert hits, f"{name}: planted {planted['type']} anchor not detected"
            assert any(planted["snippet"].split()[0] in a.snippet for a in hits), (
                f"{name}: {planted['type']} snippet mismatch"
            )


def test_control_brd_is_clean(parsed: dict[str, ParsedBrd]) -> None:
    doc = parsed["BRD-AUR-26-02-konsolide-fatura.docx"]
    assert doc.doc_anchors == ()
    assert doc.open_points == ()
    assert len(doc.requirements) == 6
    assert all(r.extraction == "table" for r in doc.requirements)
    assert all(r.acceptance_criteria for r in doc.requirements)
    assert all((r.ambiguity_score or 0) < 0.3 for r in doc.requirements)


def test_templated_brd_ids_and_counts(parsed: dict[str, ParsedBrd]) -> None:
    doc = parsed["BRD-AUR-26-01-taksitlendirme.docx"]
    assert [r.id for r in doc.requirements] == [f"REQ-G-0{i}" for i in range(1, 9)]
    assert doc.brd_ref == "AUR-BRD-2026-041"
    # Assumptions (V-xx) are quarantined, never requirements.
    assert not any("V-0" in r.id for r in doc.requirements)


def test_planted_ambiguities_flagged(parsed: dict[str, ParsedBrd]) -> None:
    doc = parsed["BRD-AUR-26-01-taksitlendirme.docx"]
    by_id = {r.id: r for r in doc.requirements}
    # G-04 'farklı koşullar uygulanabilir' must fail the gate outright.
    assert (by_id["REQ-G-04"].ambiguity_score or 0) >= GATE_THRESHOLD
    # G-07's gap is semantic (return-flow acceptance); the rule floor must at least
    # flag the missing acceptance criterion — the LLM blend refines it further.
    assert "missing-acceptance-criteria" in by_id["REQ-G-07"].ambiguity_issues
    # The clean, measurable requirement stays low.
    assert (by_id["REQ-G-02"].ambiguity_score or 0) < 0.3


def test_messy_brd_yields_heuristic_candidates(parsed: dict[str, ParsedBrd]) -> None:
    doc = parsed["BRD-AUR-26-03-bayi-siparis-entegrasyonu.docx"]
    assert len(doc.requirements) >= 3
    assert all(r.extraction == "heuristic" for r in doc.requirements)
    assert all(r.id.startswith("REQ-H") for r in doc.requirements)
    flagged = [r for r in doc.requirements if (r.ambiguity_score or 0) >= GATE_THRESHOLD]
    assert len(flagged) >= 2, "messy BRD should push most candidates to the gate"
    assert any("toplantıda" in p.lower() for p in doc.open_points)


def test_micro_cr(parsed: dict[str, ParsedBrd]) -> None:
    doc = parsed["BRD-AUR-26-04-bakiye-tasima.docx"]
    assert len(doc.requirements) == 1
    assert doc.brd_ref == "AUR-CR-2026-118"
    assert any("netleştirilecek" in p for p in doc.open_points)


def test_table_counts_match_manifest(parsed: dict[str, ParsedBrd]) -> None:
    for name, entry in BY_FILE.items():
        assert parsed[name].table_count == entry["tables"], name


def test_ids_stable_across_reparses() -> None:
    name = "BRD-AUR-26-03-bayi-siparis-entegrasyonu.docx"
    first = [r.id for r in parse_brd(FIXTURES / name).requirements]
    second = [r.id for r in parse_brd(FIXTURES / name).requirements]
    assert first == second
