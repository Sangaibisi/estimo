"""Core domain models shared by every Estimo component."""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

PERSON_DAY: Literal["person_day"] = "person_day"

# Shared SQLAlchemy naming convention (constraint names stay stable across services).
SQL_NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

_EVIDENCE_SCHEMES: dict[str, str] = {
    "repo": "code",
    "wiki": "wiki",
    "ledger": "ledger",
    "answer": "answer",
    "note": "note",
}


class EvidenceKind(StrEnum):
    CODE = "code"
    WIKI = "wiki"
    LEDGER = "ledger"
    ANSWER = "answer"
    # Non-resolvable annotation (e.g. note://no-analogs) — keeps ledger:// = UUID ids only.
    NOTE = "note"


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
    ledger://<entryId> · answer://<questionId> · note://<slug> (annotation, non-resolvable)
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
    extraction: Literal["coded", "table", "heuristic"] = "coded"
    acceptance_criteria: str | None = None
    anchors: tuple[AnchorFlag, ...] = ()
    ambiguity_score: float | None = Field(default=None, ge=0, le=1)
    ambiguity_issues: tuple[str, ...] = ()


class ClarificationQuestion(EstimoModel):
    """One question the gate raised, and where it is in the customer loop.

    `status` walks open → sent → answered → applied. It existed from the start and
    nothing ever advanced it, so the board could only ever show two lanes and the
    dispatch itself — when it went out, to whom, how long it has been waiting — was
    never recorded anywhere. The timestamps below are what make "waiting 3 days" a
    fact rather than a guess.
    """

    id: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    # The ambiguity rules that raised this question, frozen at ASK time.
    #
    # `reason` is prose for a human, and when a gateway is configured the LLM rewrites
    # it — so counting reasons by parsing that sentence silently becomes a count of the
    # offline subset. These codes are the machine-readable half and are never rewritten.
    #
    # Frozen matters as much as machine-readable: the gate re-scores a requirement once
    # its answer is folded in, so the requirement's LIVE issues describe the state after
    # the question did its job. `missing-acceptance-criteria` disappears from exactly the
    # requirement whose question was raised for missing acceptance criteria.
    issue_codes: tuple[str, ...] = ()
    status: Literal["open", "sent", "answered", "applied"] = "open"
    answer: str | None = None
    sent_at: dt.datetime | None = None
    recipient: str | None = None
    answered_at: dt.datetime | None = None
    answered_by: str | None = None
    # The work item this answer was folded into, once the estimate was rebuilt.
    applied_to: str | None = None


class WorkItem(EstimoModel):
    id: str = Field(min_length=1)
    brd_ref: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str | None = None
    requirement_ids: tuple[str, ...] = Field(min_length=1)
    module_tags: tuple[str, ...] = ()
    domain_tags: tuple[str, ...] = ()
    team: str | None = None
    anchors: tuple[AnchorFlag, ...] = Field(
        default=(),
        description="Quarantined anchors inherited from the source requirements — "
        "estimation prompts MUST redact these (PRINCIPLES #5).",
    )


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


class ImpactClaim(EstimoModel):
    """One claim of the impact analysis. Structurally cannot exist without evidence
    (PRINCIPLES #2 — same rule as EstimateLine): the worker VERIFIES every ref
    resolves before a claim is kept, and drops the claim otherwise."""

    text: str = Field(min_length=1)
    # Set for module-touchpoint claims so the Impact Map can dock the evidence
    # under the module it belongs to; integration/risk claims may leave it None.
    module: str | None = None
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1)


class DisciplineShare(EstimoModel):
    """A proposed share of one work item's effort for one discipline (S13-3).

    Model-proposed until the discipline's calibration slice clears MIN_SAMPLES —
    consumers render the split with a "model-proposed, uncalibrated" badge, the
    S12-7 honest-silence pattern."""

    discipline: Literal["frontend", "backend"]
    share: float = Field(ge=0, le=1)
    rationale: str | None = None


class ImpactAnalysis(EstimoModel):
    """Structured scope/impact reasoning for one work item (ADR-0009, S13-2).

    Produced by the agentic worker (`source="agentic"`) or by the deterministic
    graph heuristic when no model is available (`source="deterministic"`). Every
    kept claim's evidence resolved at build time; `dropped_claims` counts what
    verification removed, so a thin analysis is visibly thin rather than silently
    filtered."""

    work_item_id: str = Field(min_length=1)
    repos: tuple[str, ...] = ()
    modules: tuple[ImpactClaim, ...] = ()
    integration_points: tuple[ImpactClaim, ...] = ()
    discovery_risks: tuple[ImpactClaim, ...] = ()
    composition: tuple[DisciplineShare, ...] = ()
    confidence: Confidence = Confidence.LOW
    source: Literal["agentic", "deterministic"]
    dropped_claims: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _composition_shares_sum_to_one(self) -> Self:
        if self.composition:
            total = sum(share.share for share in self.composition)
            if not 0.99 <= total <= 1.01:
                msg = f"composition shares must sum to 1.0, got {total}"
                raise ValueError(msg)
            disciplines = [share.discipline for share in self.composition]
            if len(disciplines) != len(set(disciplines)):
                msg = "composition may not repeat a discipline"
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
    # Per-work-item impact analyses (S13-2). Part of the document because they ARE
    # basis-of-estimate material: versioned and frozen with the rest of the draft.
    # Default () keeps every stored pre-S13 document valid on re-validation.
    impact: tuple[ImpactAnalysis, ...] = ()

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
