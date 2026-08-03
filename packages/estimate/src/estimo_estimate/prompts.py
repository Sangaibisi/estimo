"""Versioned prompt loading for the estimate package (same contract as S4-7)."""

from __future__ import annotations

from pathlib import Path

from estimo_pipeline.prompts import _HEADER_RE, Prompt

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_estimate_prompt() -> Prompt:
    path = _PROMPTS_DIR / "estimate.md"
    raw = path.read_text(encoding="utf-8")
    match = _HEADER_RE.search(raw)
    if match is None or match.group("name") != "estimate":
        msg = f"prompt file {path.name} lacks a valid '<!-- prompt: estimate vN -->' header"
        raise ValueError(msg)
    return Prompt(
        name="estimate", version=int(match.group("version")), text=raw[match.end() :].strip()
    )
