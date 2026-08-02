"""Core domain models shared by every Estimo component."""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

PERSON_DAY: Literal["person_day"] = "person_day"

_EVIDENCE_SCHEMES: dict[str, str] = {
    "repo": "code",
    "wiki": "wiki",
    "ledger": "ledger",
    "answer": "answer",
}


class EvidenceKind(StrEnum):
    CODE = "code"
    WIKI = "wiki"
    LEDGER = "ledger"
    ANSWER = "answer"


class ConeStage(StrEnum):
    """Cone-of-uncertainty stage a BoE is issued at (PRINCIPLES #1)."""

    CONCEPT = "concept"
    APPROVED_SCOPE = "approved_scope"
    DETAILED = "detailed"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EstimoModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class EvidenceRef(EstimoModel):
    """A provenance link carried by every estimate line (PRINCIPLES #2).

    URI schemes: repo://<repo>@<sha>/<path>#L<a>-L<b> · wiki://<pageId>@<version> ·
    ledger://<entryId> · answer://<questionId>
    """

    uri: str = Field(min_length=1)
    kind: EvidenceKind
    label: str | None = None

    @model_validator(mode="after")
    def _scheme_matches_kind(self) -> Self:
        scheme, sep, rest = self.uri.partition("://")
        if not sep or not rest:
            msg = f"evidence uri must look like '<scheme>://<ref>', got {self.uri!r}"
            raise ValueError(msg)
        expected = _EVIDENCE_SCHEMES.get(scheme)
        if expected is None:
            msg = f"unknown evidence scheme {scheme!r}; allowed: {sorted(_EVIDENCE_SCHEMES)}"
            raise ValueError(msg)
        if expected != self.kind.value:
            msg = f"scheme {scheme!r} implies kind {expected!r}, got {self.kind.value!r}"
            raise ValueError(msg)
        return self

    @classmethod
    def from_uri(cls, uri: str, label: str | None = None) -> EvidenceRef:
        scheme = uri.partition("://")[0]
        kind = _EVIDENCE_SCHEMES.get(scheme)
        if kind is None:
            msg = f"unknown evidence scheme {scheme!r}; allowed: {sorted(_EVIDENCE_SCHEMES)}"
            raise ValueError(msg)
        return cls(uri=uri, kind=EvidenceKind(kind), label=label)


class ThreePoint(EstimoModel):
    """Three-point effort range in person-days; never a bare number (PRINCIPLES #1)."""

    optimistic: float = Field(ge=0)
    likely: float = Field(ge=0)
    pessimistic: float = Field(ge=0)
    unit: Literal["person_day"] = PERSON_DAY

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not (self.optimistic <= self.likely <= self.pessimistic):
            msg = (
                "three-point range must satisfy optimistic <= likely <= pessimistic, "
                f"got {self.optimistic} / {self.likely} / {self.pessimistic}"
            )
            raise ValueError(msg)
        return self

    def __add__(self, other: ThreePoint) -> ThreePoint:
        return ThreePoint(
            optimistic=self.optimistic + other.optimistic,
            likely=self.likely + other.likely,
            pessimistic=self.pessimistic + other.pessimistic,
        )


class AnchorFlag(EstimoModel):
    """A quarantined numeric anchor found in the BRD (PRINCIPLES #5).

    Visible to humans, stripped from estimation prompts.
    """

    type: Literal["budget", "deadline", "analogy", "effort_hint"]
    snippet: str = Field(min_length=1)


class Requirement(EstimoModel):
    id: str = Field(pattern=r"^REQ-[A-Za-z0-9][A-Za-z0-9-]*$")
    text: str = Field(min_length=1)
    source_ref: str | None = None
    language: str = "tr"
    anchors: tuple[AnchorFlag, ...] = ()
    ambiguity_score: float | None = Field(default=None, ge=0, le=1)


class ClarificationQuestion(EstimoModel):
    id: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    status: Literal["open", "sent", "answered", "applied"] = "open"
    answer: str | None = None


class WorkItem(EstimoModel):
    id: str = Field(min_length=1)
    brd_ref: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str | None = None
    requirement_ids: tuple[str, ...] = Field(min_length=1)
    module_tags: tuple[str, ...] = ()
    domain_tags: tuple[str, ...] = ()
    team: str | None = None


class AssumptionRisk(EstimoModel):
    kind: Literal["assumption", "risk"]
    text: str = Field(min_length=1)
    contingency_pd: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _contingency_only_for_risks(self) -> Self:
        if self.kind == "assumption" and self.contingency_pd is not None:
            msg = "contingency_pd applies to risks only"
            raise ValueError(msg)
        return self


class EstimateLine(EstimoModel):
    """One estimated work item. Structurally cannot exist without evidence."""

    work_item_id: str = Field(min_length=1)
    range: ThreePoint
    confidence: Confidence
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1)
    assumptions: tuple[AssumptionRisk, ...] = ()
    risks: tuple[AssumptionRisk, ...] = ()
    basis_note: str | None = None

    @model_validator(mode="after")
    def _registers_typed_correctly(self) -> Self:
        if any(a.kind != "assumption" for a in self.assumptions):
            msg = "assumptions register may contain kind='assumption' entries only"
            raise ValueError(msg)
        if any(r.kind != "risk" for r in self.risks):
            msg = "risks register may contain kind='risk' entries only"
            raise ValueError(msg)
        return self


class Signature(EstimoModel):
    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    scope: str = "full"
    signed_at: dt.datetime | None = None


class BoeDocument(EstimoModel):
    """Basis-of-Estimate draft: the product's output artifact."""

    brd_ref: str = Field(min_length=1)
    title: str = Field(min_length=1)
    cone_stage: ConeStage
    locale: str = "tr"
    lines: tuple[EstimateLine, ...] = ()
    questions: tuple[ClarificationQuestion, ...] = ()
    global_assumptions: tuple[AssumptionRisk, ...] = ()
    global_risks: tuple[AssumptionRisk, ...] = ()
    signatures: tuple[Signature, ...] = ()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total(self) -> ThreePoint:
        total = ThreePoint(optimistic=0, likely=0, pessimistic=0)
        for line in self.lines:
            total = total + line.range
        return total


class LedgerEntry(EstimoModel):
    """One imported or recorded history row (docs/LEDGER-SCHEMA.md).

    Exactly one of `estimate` (three-point) or `estimate_single` (legacy point value,
    flagged) must be present.
    """

    brd_ref: str = Field(min_length=1)
    item_title: str = Field(min_length=1)
    item_description: str | None = None
    module_tags: tuple[str, ...] = ()
    domain_tags: tuple[str, ...] = ()
    team: str | None = None
    estimate: ThreePoint | None = None
    estimate_single: float | None = Field(default=None, ge=0)
    estimated_at: dt.date | None = None
    method: Literal["expert", "planning-poker", "delphi", "estimo-hybrid"] | None = None
    actual_effort: float | None = Field(default=None, ge=0)
    actual_source: Literal["timesheet", "project-report", "expert-recall"] | None = None
    completed_at: dt.date | None = None
    scope_changed: bool = False

    @model_validator(mode="after")
    def _estimate_shape(self) -> Self:
        if (self.estimate is None) == (self.estimate_single is None):
            msg = "exactly one of estimate (three-point) or estimate_single must be set"
            raise ValueError(msg)
        if self.actual_effort is not None and self.actual_source is None:
            msg = "actual_source is required when actual_effort is present"
            raise ValueError(msg)
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def point_only(self) -> bool:
        return self.estimate_single is not None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def deviation(self) -> float | None:
        """actual / likely — None until an actual exists (or likely is zero)."""
        if self.actual_effort is None:
            return None
        likely = self.estimate.likely if self.estimate else self.estimate_single
        if not likely:
            return None
        return self.actual_effort / likely
