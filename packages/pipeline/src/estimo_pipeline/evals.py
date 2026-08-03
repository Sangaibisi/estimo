"""Offline eval harness v1 (S4-6): gate correctness + module attribution vs golden refs.

Runs the deterministic pipeline (no LLM) over the fixture BRDs and scores against the
human-authored references. Reports ALWAYS include the naive baseline delta
(PRINCIPLES #7): naive = assign the corpus-majority module to every requirement.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from estimo_pipeline.graph import run_brd
from estimo_pipeline.state import PipelineState


@dataclass
class EvalResult:
    per_brd: dict[str, dict[str, object]] = field(default_factory=dict)
    module_correct: int = 0
    module_total: int = 0
    naive_correct: int = 0
    gate_failures: list[str] = field(default_factory=list)
    question_gaps: list[str] = field(default_factory=list)
    prompt_ids: dict[str, str] = field(default_factory=dict)

    @property
    def module_accuracy(self) -> float:
        return self.module_correct / self.module_total if self.module_total else 0.0

    @property
    def naive_accuracy(self) -> float:
        return self.naive_correct / self.module_total if self.module_total else 0.0


def _majority_module(refs: dict[str, object]) -> str:
    counts: Counter[str] = Counter()
    for brd_ref in refs.values():
        primary = brd_ref.get("primary_module", {}) if isinstance(brd_ref, dict) else {}
        counts.update(str(v) for v in primary.values())
    return counts.most_common(1)[0][0] if counts else "billing-core"


async def evaluate(fixtures_dir: Path, refs_path: Path) -> EvalResult:
    golden = json.loads(refs_path.read_text(encoding="utf-8"))["brds"]
    naive_module = _majority_module(golden)
    result = EvalResult()

    for name, ref in golden.items():
        state: PipelineState = await run_brd(fixtures_dir / name, thread_id=f"eval-{name}")
        blocked = set(state.blocked_ids)
        items_by_req = {item.requirement_ids[0]: item for item in state.work_items}
        misses: list[str] = []
        brd_report: dict[str, object] = {
            "blocked": sorted(blocked),
            "work_items": len(state.work_items),
            "questions": len(state.questions),
            "module_misses": misses,
        }

        expected_gated = set(ref.get("expected_gated", []))
        if ref.get("all_gated"):
            if len(blocked) != len(state.requirements):
                result.gate_failures.append(f"{name}: expected every requirement gated")
        elif "min_gated" in ref:
            if len(blocked) < int(ref["min_gated"]):
                result.gate_failures.append(
                    f"{name}: expected >= {ref['min_gated']} gated, got {len(blocked)}"
                )
        else:
            if blocked != expected_gated:
                result.gate_failures.append(
                    f"{name}: gate mismatch expected={sorted(expected_gated)} got={sorted(blocked)}"
                )

        for req_id, expected_primary in ref.get("primary_module", {}).items():
            result.module_total += 1
            item = items_by_req.get(req_id)
            actual_primary = item.module_tags[0] if item and item.module_tags else None
            if actual_primary == expected_primary:
                result.module_correct += 1
            else:
                misses.append(f"{req_id}: expected {expected_primary}, got {actual_primary}")
            if expected_primary == naive_module:
                result.naive_correct += 1

        answered = {q.requirement_id for q in state.questions}
        for req_id in blocked:
            if req_id not in answered:
                result.question_gaps.append(f"{name}: {req_id} blocked without a question")
        for question in state.questions:
            if not question.question.strip().endswith("?"):
                result.question_gaps.append(f"{name}: {question.id} not a question")

        clear_allowed = ref.get("allowed_clear_modules")
        if clear_allowed:
            for item in state.work_items:
                if item.module_tags and item.module_tags[0] not in clear_allowed:
                    misses.append(
                        f"{item.requirement_ids[0]}: {item.module_tags[0]} outside {clear_allowed}"
                    )
        result.per_brd[name] = brd_report
        result.prompt_ids.update(state.prompt_ids)

    return result


def render_report(result: EvalResult, *, today: str) -> str:
    lines = [
        f"# S4 offline eval — {today}",
        "",
        "Deterministic pipeline (no LLM refinement) over the Aurora fixture BRDs vs the",
        "human-authored golden references. AI-arm only: the human and hybrid arms of the",
        "F1 blinded protocol require human estimators (evals/README.md).",
        "",
        (
            f"- Module attribution accuracy: **{result.module_accuracy:.0%}** "
            f"({result.module_correct}/{result.module_total})"
        ),
        (
            f"- Naive baseline (majority module): {result.naive_accuracy:.0%} — "
            f"delta **{result.module_accuracy - result.naive_accuracy:+.0%}**"
        ),
        f"- Gate failures: {len(result.gate_failures)}",
        f"- Question gaps: {len(result.question_gaps)}",
        f"- Prompt versions: {result.prompt_ids or 'deterministic-only'}",
        "",
    ]
    for name, report in result.per_brd.items():
        lines.append(f"## {name}")
        for key, value in report.items():
            lines.append(f"- {key}: {value}")
        lines.append("")
    for failure in result.gate_failures:
        lines.append(f"GATE FAILURE: {failure}")
    for gap in result.question_gaps:
        lines.append(f"QUESTION GAP: {gap}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(prog="estimo-eval")
    parser.add_argument("--fixtures", type=Path, default=Path("fixtures/brd"))
    parser.add_argument("--refs", type=Path, default=Path("evals/golden/decomposition/refs.json"))
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--date", required=True, help="Report date (YYYY-MM-DD)")
    args = parser.parse_args()
    result = asyncio.run(evaluate(args.fixtures, args.refs))
    args.report.write_text(render_report(result, today=args.date), encoding="utf-8")
    print(render_report(result, today=args.date))
    if result.gate_failures or result.question_gaps:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
