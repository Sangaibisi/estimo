"""S4-6/S4-7: the offline eval harness runs in CI on every PR — a prompt or pipeline
change that regresses decomposition or the gate cannot merge silently."""

from pathlib import Path

import pytest
from estimo_pipeline.evals import EvalResult, evaluate, render_report

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
async def result() -> EvalResult:
    return await evaluate(
        REPO_ROOT / "fixtures" / "brd",
        REPO_ROOT / "evals" / "golden" / "decomposition" / "refs.json",
    )


async def test_gate_matches_golden_references(result: EvalResult) -> None:
    assert result.gate_failures == []


async def test_every_blocked_requirement_has_a_question(result: EvalResult) -> None:
    assert result.question_gaps == []


async def test_module_attribution_beats_threshold_and_naive(result: EvalResult) -> None:
    assert result.module_accuracy >= 0.85, render_report(result, today="ci")
    assert result.module_accuracy > result.naive_accuracy, "must beat the naive baseline"
