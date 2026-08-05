"""Versioned prompt loading for the estimate package (same contract as S4-7)."""

from __future__ import annotations

from pathlib import Path

from estimo_pipeline.prompts import HEADER_RE, Prompt

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_package_prompt(name: str) -> Prompt:
    path = _PROMPTS_DIR / f"{name}.md"
    raw = path.read_text(encoding="utf-8")
    match = HEADER_RE.search(raw)
    if match is None or match.group("name") != name:
        msg = f"prompt file {path.name} lacks a valid '<!-- prompt: {name} vN -->' header"
        raise ValueError(msg)
    return Prompt(name=name, version=int(match.group("version")), text=raw[match.end() :].strip())


def load_estimate_prompt() -> Prompt:
    return load_package_prompt("estimate")


def load_impact_prompt() -> Prompt:
    return load_package_prompt("impact")
