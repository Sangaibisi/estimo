"""Anchor quarantine detection (PRINCIPLES #5).

Deterministic Turkish-first patterns for numeric anchors a BRD smuggles toward the
estimator: budgets, deadlines, effort analogies and bare effort hints. Detected anchors
stay visible to humans and are stripped from estimation prompts by the pipeline.

Patterns are order-symmetric within a sentence: "azami 90 adam-gün" and
"90 adam-günü aşmayacak şekilde bütçelendi" both match.
"""

from __future__ import annotations

import re

from estimo_core import AnchorFlag

_TR_MONTHS = "Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|Eylül|Ekim|Kasım|Aralık"

_EFFORT_UNIT = r"(?:adam[- ]gün|adam[- ]saat|kişi[- ]gün|gün|hafta)"
_NUM_EFFORT = r"\d+[.,]?\d*\s*" + _EFFORT_UNIT

_BUDGET_KW = r"(?:bütçe\w*|azami|en fazla|ayrılan|üst sınır)"
_BUDGET_RE = re.compile(
    r"[^.]*(?:\b"
    + _BUDGET_KW
    + r"[^.]*?"
    + _NUM_EFFORT
    + r"|"
    + _NUM_EFFORT
    + r"[^.]*?\b"
    + _BUDGET_KW
    + r")[^.]*",
    re.IGNORECASE,
)

_DATE = r"(?:\d{1,2}\s+(?:" + _TR_MONTHS + r")\s+\d{4}|\d{2}\.\d{2}\.\d{4})"
_DEADLINE_KW = (
    r"(?:yetiş\w*|teslim\w*|lansman\w*|canlıya|kadar tamamlan\w*|son tarih|"
    r"hedef tarih\w*|planlan\w*)"
)
_DEADLINE_RE = re.compile(
    r"[^.]*(?:"
    + _DATE
    + r"[^.]*?"
    + _DEADLINE_KW
    + r"|"
    + _DEADLINE_KW
    + r"[^.]*?"
    + _DATE
    + r")[^.]*",
    re.IGNORECASE,
)

_ANALOGY_RE = re.compile(
    r"[^.]*\bgeçen\s+(?:yıl|sene|sefer|ay)[^.]*?\d+\s*" + _EFFORT_UNIT + r"[^.]*",
    re.IGNORECASE,
)
_EFFORT_HINT_RE = re.compile(
    r"[^.]*?\d+\s*" + _EFFORT_UNIT + r"[^.]*?(?:sürer|biteceğini|tamamlanır|yeterli)[^.]*",
    re.IGNORECASE,
)

_DETECTORS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("budget", _BUDGET_RE),
    ("deadline", _DEADLINE_RE),
    ("analogy", _ANALOGY_RE),
    ("effort_hint", _EFFORT_HINT_RE),
)


def redact_anchors(text: str) -> str:
    """Replace anchor-bearing sentences with quarantine markers (PRINCIPLES #5).

    Uses the SAME detection regexes, so anything detectable is guaranteed redacted —
    substring replacement of stored snippets would miss whitespace-normalized copies.
    Humans keep seeing the raw text; only LLM prompt boundaries use this.
    """
    for anchor_type, pattern in _DETECTORS:
        text = pattern.sub(f" [{anchor_type}-karantina] ", text)
    return text


def detect_anchors(text: str) -> tuple[AnchorFlag, ...]:
    """Return anchors found in `text`, first match per type, snippet-trimmed."""
    found: list[AnchorFlag] = []
    for anchor_type, pattern in _DETECTORS:
        match = pattern.search(text)
        if match is None:
            continue
        snippet = " ".join(match.group(0).split()).strip(" ;,")
        if anchor_type == "effort_hint" and any(f.snippet == snippet for f in found):
            # An analogy sentence usually also matches the bare hint pattern; keep the
            # more specific classification only.
            continue
        found.append(AnchorFlag(type=anchor_type, snippet=snippet[:200]))
    return tuple(found)
