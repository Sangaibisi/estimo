"""Pipeline state: one BRD's journey from parse to estimation-ready work items."""

from __future__ import annotations

from typing import Literal

from estimo_parse import ParsedBrd
from pydantic import BaseModel, ConfigDict, Field

from estimo_core import ClarificationQuestion, Requirement, WorkItem


class PipelineState(BaseModel):
    """Serializable state (the CLI persists it as JSON between run and resume)."""

    model_config = ConfigDict(extra="forbid")

    source_path: str
    parsed: ParsedBrd | None = None
    requirements: tuple[Requirement, ...] = ()
    blocked_ids: tuple[str, ...] = Field(
        default=(),
        description="Requirements failing the ambiguity gate — cannot enter estimation "
        "(PRINCIPLES #3).",
    )
    questions: tuple[ClarificationQuestion, ...] = ()
    answers: dict[str, str] = Field(
        default_factory=dict, description="question id -> customer answer"
    )
    work_items: tuple[WorkItem, ...] = ()
    unmapped_ids: tuple[str, ...] = Field(
        default=(), description="Clear requirements without any module attribution"
    )
    status: Literal["created", "parsed", "gated", "awaiting_answers", "ready_for_estimation"] = (
        "created"
    )
    prompt_ids: dict[str, str] = Field(
        default_factory=dict, description="prompt name -> versioned id used in this run"
    )
