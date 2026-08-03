"""Parse-stage output model."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from estimo_core import AnchorFlag, Requirement


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
