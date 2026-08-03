"""Shared Turkish text helpers."""

from __future__ import annotations


def tr_lower(text: str) -> str:
    """Turkish-aware lowering: İ→i and I→ı BEFORE str.lower(), which would otherwise
    produce i̇ (combining dot) and break substring matches on caps/İ-initial text."""
    return text.replace("İ", "i").replace("I", "ı").lower()
