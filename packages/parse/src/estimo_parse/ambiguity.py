"""Ambiguity pre-score v0: deterministic rules + optional LLM blend (S2-4).

The rule score is the offline-testable floor; the LLM blend refines it through the
gateway when available. Unclear requirements never reach estimation (PRINCIPLES #3) —
this module only *scores*; the gate itself lives in the pipeline (S4).
"""

from __future__ import annotations

import json
import re

from estimo_core import Requirement, tr_lower
from estimo_gateway import GatewayClient

GATE_THRESHOLD = 0.5

_VAGUE_TERMS = (
    "uygulanabilir",
    "gerekiyorsa",
    "gerektiğinde",
    "farklı koşullar",
    "netleştirilecek",
    "belirlenecek",
    "karar verilecek",
    "detayları",
    "vb.",
    "vs.",
    "olabilir",
    "ileride",
    "şimdilik",
    "gibi durumlar",
)
_CONDITION_RE = re.compile(r"(durumunda|halinde|olması hâlinde)", re.IGNORECASE)
_MEASURABLE_RE = re.compile(r"\d|yüzde|oran|adet|saniye|dakika|saat|gün|ay\b", re.IGNORECASE)


def rule_score(req: Requirement) -> tuple[float, tuple[str, ...]]:
    """Deterministic score in [0, 1] with machine-readable issue slugs."""
    text = tr_lower(req.text)
    score = 0.0
    issues: list[str] = []

    vague_hits = [term for term in _VAGUE_TERMS if term in text]
    if vague_hits:
        score += min(0.25 + 0.15 * (len(vague_hits) - 1), 0.5)
        issues.append("vague-terms:" + ",".join(vague_hits[:3]))

    if req.acceptance_criteria is None:
        # No explicit acceptance criterion and nothing measurable in the text itself.
        if not _MEASURABLE_RE.search(text):
            score += 0.35
            issues.append("missing-acceptance-criteria")
        else:
            score += 0.15
            issues.append("implicit-acceptance-only")

    if _CONDITION_RE.search(text) and any(
        term in text for term in ("netleştir", "belirlen", "karar veril")
    ):
        score += 0.3
        issues.append("undefined-condition-outcome")

    if req.extraction == "heuristic":
        score += 0.2
        issues.append("unstructured-source")

    return min(score, 1.0), tuple(issues)


_LLM_PROMPT = (
    "You assess one requirement from a Turkish telco BRD for ambiguity. "
    'Reply with ONLY a JSON object: {"score": <0..1>, "issues": [<short slugs>]}. '
    "Score 0 = fully estimable as written; 1 = cannot be estimated without answers. "
    "Judge: missing actor/scope, undefined terms, missing acceptance criteria, "
    "unresolved conditions. The requirement text (Turkish, keep untranslated):\n"
)


async def llm_score(client: GatewayClient, req: Requirement) -> tuple[float, tuple[str, ...]]:
    """LLM refinement via the gateway ('reading' stage). Raises GatewayError upward."""
    result = await client.complete(
        "reading",
        [{"role": "user", "content": _LLM_PROMPT + req.text}],
        temperature=0.0,
        max_tokens=200,
    )
    try:
        payload = json.loads(result.text)
        score = float(payload["score"])
        issues = tuple(str(issue) for issue in payload.get("issues", []))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        # Unusable LLM output must never mask the rule floor.
        return 0.0, ("llm-output-unparseable",)
    return max(0.0, min(score, 1.0)), issues


def blend(
    rule: tuple[float, tuple[str, ...]], llm: tuple[float, tuple[str, ...]]
) -> tuple[float, tuple[str, ...]]:
    """Blend = the more pessimistic score; issues unioned, rule first."""
    score = max(rule[0], llm[0])
    issues = rule[1] + tuple(issue for issue in llm[1] if issue not in rule[1])
    return score, issues
