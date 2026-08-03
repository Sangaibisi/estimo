"""Estimo parse — BRD ingestion (S2).

Turkish `.docx` BRD → stable-ID requirements table with quarantined anchors and
ambiguity pre-scores.
"""

from estimo_parse.ambiguity import GATE_THRESHOLD, blend, llm_score, rule_score
from estimo_parse.anchors import detect_anchors
from estimo_parse.models import ParsedBrd
from estimo_parse.segment import parse_brd

__all__ = [
    "GATE_THRESHOLD",
    "ParsedBrd",
    "blend",
    "detect_anchors",
    "llm_score",
    "parse_brd",
    "rule_score",
]
