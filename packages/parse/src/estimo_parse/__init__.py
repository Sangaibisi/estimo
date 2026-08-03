"""Estimo parse — BRD ingestion (S2).

Turkish `.docx` BRD → stable-ID requirements table with quarantined anchors and
ambiguity pre-scores.
"""

from estimo_parse.ambiguity import DATA_SYSTEM, GATE_THRESHOLD, blend, fence, llm_score, rule_score
from estimo_parse.anchors import detect_anchors, redact_anchors
from estimo_parse.models import ParsedBrd
from estimo_parse.segment import parse_brd

__all__ = [
    "DATA_SYSTEM",
    "GATE_THRESHOLD",
    "ParsedBrd",
    "blend",
    "detect_anchors",
    "fence",
    "llm_score",
    "parse_brd",
    "redact_anchors",
    "rule_score",
]
