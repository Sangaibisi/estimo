"""Consistency critic (S6-5): deterministic checks over an assembled BoE draft.

Structural laws (evidence ≥ 1, band ordering) are already type-enforced; the critic
catches the semantic layer: duplicate items, gate leakage, implausible spreads,
prior-based bands presented without their assumption. Findings are returned, never
swallowed — the caller decides between annotate and refuse.
"""

from __future__ import annotations

from estimo_pipeline import PipelineState

from estimo_core import BoeDocument

MAX_SPREAD_RATIO = 10.0


def review_boe(boe: BoeDocument, state: PipelineState) -> list[str]:
    findings: list[str] = []

    seen: set[str] = set()
    for line in boe.lines:
        if line.work_item_id in seen:
            findings.append(f"duplicate estimate line for {line.work_item_id}")
        seen.add(line.work_item_id)

    items_by_id = {item.id: item for item in state.work_items}
    blocked = set(state.blocked_ids)
    for line in boe.lines:
        item = items_by_id.get(line.work_item_id)
        if item is None:
            findings.append(f"{line.work_item_id}: line without a matching work item")
            continue
        if blocked & set(item.requirement_ids):
            findings.append(
                f"{line.work_item_id}: GATE LEAK — blocked requirement estimated (PRINCIPLES #3)"
            )
        if line.range.optimistic > 0 and (
            line.range.pessimistic / max(line.range.optimistic, 0.01) > MAX_SPREAD_RATIO
        ):
            findings.append(
                f"{line.work_item_id}: spread ratio exceeds {MAX_SPREAD_RATIO}x — "
                "verify the analogs"
            )

    estimated = {line.work_item_id for line in boe.lines}
    for item in state.work_items:
        if item.id not in estimated:
            findings.append(f"{item.id}: work item has no estimate line")

    prior_lines = [line for line in boe.lines if "prior" in (line.basis_note or "")]
    if prior_lines and not any("öncül" in assumption.text for assumption in boe.global_assumptions):
        findings.append("prior-based bands present without a global cold-start assumption")

    return findings
