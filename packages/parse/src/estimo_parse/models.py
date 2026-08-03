"""Parse-stage output model."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from estimo_core import AnchorFlag, Requirement

# How much document body a parsed BRD may carry, measured as SERIALIZED JSON bytes —
# the thing that actually lands in the JSONB column every state read touches.
#
# The first cut budgeted block TEXT instead, which sounds equivalent and is not: each
# block also carries its index, kind, level, the full heading trail, a source_ref that
# repeats that trail, its anchors, and ~70 bytes of JSON keys. Measured on this repo's
# own fixture that is 3.6x; on a document of many short paragraphs under a deep
# heading trail it reached 545x, so a 12 KB .docx could persist an 18 MB row while the
# budget reported itself satisfied. Budget the bytes you are actually spending.
MAX_BODY_BYTES = 400_000

# No single block may dominate the budget — one pathological table would otherwise
# consume it and leave the rest of the document unrepresented.
MAX_BLOCK_CHARS = 8_000


class DocBlock(BaseModel):
    """One rendered unit of the source document, kept so the Reading Room can show
    the BRD beside its structured form.

    `source_ref` uses the same string a Requirement carries, which is what lets a row
    and its paragraph find each other without a second identifier scheme.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    index: int
    kind: Literal["title", "heading", "paragraph", "list_item", "table"]
    text: str = ""
    level: int = 0
    heading_trail: tuple[str, ...] = ()
    source_ref: str
    rows: tuple[tuple[str, ...], ...] = ()
    # This block's own text was clipped to MAX_BLOCK_CHARS.
    text_truncated: bool = False
    # Quarantined material found in THIS block, so the source pane can draw the
    # same crit pill the requirements table does (PRINCIPLES #5: visible to humans,
    # withheld from the model).
    anchors: tuple[AnchorFlag, ...] = ()


class ParsedBrd(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    brd_ref: str = Field(min_length=1)
    title: str = Field(min_length=1)
    language: str = "tr"
    source_file: str
    meta: dict[str, str] = Field(default_factory=dict)
    requirements: tuple[Requirement, ...] = ()
    doc_anchors: tuple[AnchorFlag, ...] = ()
    open_points: tuple[str, ...] = Field(
        default=(),
        description="Document-level unresolved statements (e.g. 'işletme ile netleştirilecektir')",
    )
    headings: tuple[str, ...] = ()
    table_count: int = 0
    # Document body for the Reading Room's source pane. Empty on estimates parsed
    # before this shipped — the pane says so instead of pretending the BRD was blank.
    #
    # `body_truncated` means blocks were dropped; kept blocks retain their original
    # `index`, so a gap in the sequence is detectable and the pane marks where the
    # document was elided instead of reading as continuous prose.
    blocks: tuple[DocBlock, ...] = ()
    body_truncated: bool = False
