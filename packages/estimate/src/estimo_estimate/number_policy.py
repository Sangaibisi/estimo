"""Number policy (S13-4, ADR-0009): where analogs exist the analog median stays
the anchor; the LLM's role around the NUMBER is bounded and auditable.

Three legs:

1. **Analog vetting** — the model may flag non-comparable analogs OUT of the
   median. Every exclusion is recorded as an assumption naming the analog and the
   stated reason, so a reviewer can audit (and reverse) the judgement. Verdicts
   for analogs that were not presented are discarded; an unparseable reply keeps
   the full set — refusing to vet is not evidence of incomparability.

2. **Analog cards in the nudge** — the within-band adjustment sees the top-k
   analog cards (title, modules, values), not just the bare band.

3. **No-analog proposal** — where retrieval finds nothing, the constant 1/3/8 pd
   prior is replaced (when a model is available) by an evidence-grounded proposal:
   cone-stage-wide band, LOW confidence, `basis_note="model-proposed,
   uncalibrated"`. The tenant's transfer quantiles are NEVER wrapped around a
   model-proposed likely — they are measured against the analog median (the
   7%-coverage note in calibration.py), and applying them to a number with a
   different error process would fake a calibration the band does not have.
"""

from __future__ import annotations

import json
import logging

from estimo_knowledge import AnalogyCard
from estimo_parse import DATA_SYSTEM, fence

from estimo_core import AssumptionRisk, ConeStage, ThreePoint
from estimo_estimate.prompts import load_package_prompt
from estimo_gateway import GatewayClient, GatewayError

logger = logging.getLogger("estimo.estimate.numbers")

MODEL_PROPOSED_BASIS = "model-proposed, uncalibrated"

# Cone-of-uncertainty floors (PRINCIPLES #1): a no-history band must be at least
# this wide around its likely. Matches the multipliers the UI presents per stage.
_CONE_SPREAD = {
    ConeStage.CONCEPT: 4.0,
    ConeStage.APPROVED_SCOPE: 1.5,
    ConeStage.DETAILED: 1.25,
}


def _card_lines(analogs: list[AnalogyCard], limit: int) -> str:
    lines = []
    for card in analogs[:limit]:
        value = card.actual_effort
        estimate = card.estimate.likely if card.estimate else card.estimate_single
        parts = [
            f"id={card.entry_id}",
            card.item_title,
            f"modules={','.join(card.module_tags) or '-'}",
            f"actual={value if value is not None else '-'} pd",
            f"estimate={estimate if estimate is not None else '-'} pd",
        ]
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def analog_context(analogs: list[AnalogyCard], *, limit: int = 3) -> str:
    """The top-k analog cards, fenced, for the within-band nudge prompt."""
    if not analogs:
        return ""
    return f"\nAnalog jobs (delivered history):\n{fence(_card_lines(analogs, limit))}"


async def vet_analogs(
    client: GatewayClient,
    item_text: str,
    analogs: list[AnalogyCard],
) -> tuple[list[AnalogyCard], list[AssumptionRisk]]:
    """The model flags non-comparable analogs out of the median — auditable.

    Returns (kept, exclusion_notes). Any failure keeps the full set. All-excluded
    is a legitimate outcome: it routes the item to the no-analog path, and every
    exclusion is printed for review, so the judgement is reversible by a human.
    """
    prompt = load_package_prompt("vet")
    presented = {str(card.entry_id): card for card in analogs}
    try:
        result = await client.complete(
            "vet",
            [
                {"role": "system", "content": DATA_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"{prompt.text}\n\nWork item:\n{fence(item_text)}\n\n"
                        f"Analogs:\n{fence(_card_lines(analogs, len(analogs)))}"
                    ),
                },
            ],
            temperature=0.0,
            max_tokens=500,
        )
        payload = json.loads(result.text)
        verdicts = payload["verdicts"] if isinstance(payload, dict) else None
        if not isinstance(verdicts, list):
            raise TypeError("expected a verdicts list")
    except (GatewayError, json.JSONDecodeError, TypeError, KeyError) as exc:
        logger.warning("analog vetting degraded (full set kept): %s", exc)
        return analogs, []

    excluded: dict[str, str] = {}
    for verdict in verdicts:
        if not isinstance(verdict, dict):
            continue
        entry_id = str(verdict.get("entry_id", ""))
        # Verdicts for analogs that were not presented are discarded — the model
        # may only judge what it was shown.
        if entry_id not in presented or verdict.get("comparable", True):
            continue
        excluded[entry_id] = str(verdict.get("reason", "")).strip() or "gerekçe verilmedi"

    kept = [card for card in analogs if str(card.entry_id) not in excluded]
    notes = [
        AssumptionRisk(
            kind="assumption",
            text=(
                f"Analog medyandan çıkarıldı ({presented[entry_id].brd_ref} — "
                f"{presented[entry_id].item_title[:80]}): {reason[:200]}"
            ),
        )
        for entry_id, reason in excluded.items()
    ]
    return kept, notes


def cone_widened(
    optimistic: float, likely: float, pessimistic: float, stage: ConeStage
) -> ThreePoint:
    """Clamp a proposed band to at least the cone floor around its likely.

    Widening only — a proposal wider than the cone keeps its width. This is what
    makes "cone-stage-wide" a property of the OUTPUT rather than a hope about the
    model's self-restraint.
    """
    spread = _CONE_SPREAD[stage]
    return ThreePoint(
        optimistic=round(min(optimistic, likely / spread), 1),
        likely=round(likely, 1),
        pessimistic=round(max(pessimistic, likely * spread), 1),
    )


async def propose_no_analog_band(
    client: GatewayClient,
    item_text: str,
    evidence_summary: str,
    stage: ConeStage,
) -> tuple[ThreePoint, str | None, list[AssumptionRisk]] | None:
    """Evidence-grounded band proposal for an item with no usable analogs.

    None on any failure — the caller falls back to the deterministic 1/3/8 prior.
    The tenant's transfer quantiles are deliberately NOT applied here (module
    docstring; the 7%-coverage note in calibration.py).
    """
    prompt = load_package_prompt("no-analog")
    evidence_block = f"\n\nEvidence:\n{fence(evidence_summary)}" if evidence_summary else ""
    try:
        result = await client.complete(
            "propose",
            [
                {"role": "system", "content": DATA_SYSTEM},
                {
                    "role": "user",
                    "content": f"{prompt.text}\n\nWork item:\n{fence(item_text)}{evidence_block}",
                },
            ],
            temperature=0.0,
            max_tokens=500,
        )
        payload = json.loads(result.text)
        if not isinstance(payload, dict):
            raise TypeError("expected JSON object")
        optimistic = float(payload["optimistic"])
        likely = float(payload["likely"])
        pessimistic = float(payload["pessimistic"])
        if not (0 < optimistic <= likely <= pessimistic):
            raise ValueError("proposed band is not ordered/positive")
        band = cone_widened(optimistic, likely, pessimistic, stage)
        rationale = str(payload.get("rationale", "")).strip() or None
        assumptions = [
            AssumptionRisk(kind="assumption", text=str(text)[:300])
            for text in payload.get("assumptions", []) or []
            if str(text).strip()
        ][:5]
    except (GatewayError, json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
        logger.warning("no-analog proposal degraded to the deterministic prior: %s", exc)
        return None
    return band, rationale, assumptions
