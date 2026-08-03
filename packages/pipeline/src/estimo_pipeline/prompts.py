"""Versioned prompt loading (S4-7).

Prompts are files, never inline strings (AGENTS §2.5). Each file starts with an HTML
comment header `<!-- prompt: <name> v<version> -->`; loading fails loudly when the
header is missing so an unversioned prompt cannot ship. Any change to these files is a
behavior change — CI runs the eval suite on every PR, so a prompt edit cannot merge
without an eval run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_HEADER_RE = re.compile(r"<!--\s*prompt:\s*(?P<name>[\w-]+)\s+v(?P<version>\d+)\s*-->")


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    text: str

    @property
    def id(self) -> str:
        return f"{self.name}-v{self.version}"


def load_prompt(name: str) -> Prompt:
    path = PROMPTS_DIR / f"{name}.md"
    raw = path.read_text(encoding="utf-8")
    match = _HEADER_RE.search(raw)
    if match is None or match.group("name") != name:
        msg = f"prompt file {path.name} lacks a valid '<!-- prompt: {name} vN -->' header"
        raise ValueError(msg)
    return Prompt(
        name=name,
        version=int(match.group("version")),
        text=raw[match.end() :].strip(),
    )
