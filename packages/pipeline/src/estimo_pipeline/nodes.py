"""Pipeline nodes: gate, question generation, decomposition.

Every node has a deterministic offline path; the gateway (when provided) refines but
never replaces the deterministic floor — an unreachable or misbehaving LLM degrades
quality, never correctness (mirrors the ambiguity-blend contract from S2).
"""

from __future__ import annotations

import json
import logging

from estimo_parse import (
    DATA_SYSTEM,
    GATE_THRESHOLD,
    blend,
    fence,
    llm_score,
    redact_anchors,
    rule_score,
)

from estimo_core import ClarificationQuestion, Requirement, WorkItem, tr_lower
from estimo_gateway import GatewayClient, GatewayError
from estimo_pipeline.prompts import load_prompt
from estimo_pipeline.state import PipelineState
from estimo_pipeline.taxonomy import modules_for

logger = logging.getLogger("estimo.pipeline")

_CLEARING_MARKER = "cevap:"
_NON_ANSWERS = {"-", "?", "yok", "bilmiyorum", "bilinmiyor", "tbd", "sonra"}


def _answer_clears(answer: str) -> bool:
    """A human answer clears the gate only if it would itself pass the gate: minimum
    content, no non-answer stopwords, and no vague/undefined signals of its own."""
    text = answer.strip()
    if len(text) < 15 or tr_lower(text) in _NON_ANSWERS:
        return False
    probe = Requirement(id="REQ-ANSWER-PROBE", text=text)
    score, issues = rule_score(probe)
    if any(issue.startswith(("vague-terms", "undefined")) for issue in issues):
        return False
    return score < GATE_THRESHOLD


async def gate_requirements(
    state: PipelineState, client: GatewayClient | None = None
) -> PipelineState:
    """Score every requirement; below-threshold ones proceed, the rest are blocked.

    An applied answer is appended to the requirement text (marked), and the item is
    re-scored — the gate re-evaluates instead of trusting the answer blindly.
    """
    parsed = state.parsed
    if parsed is None:
        msg = "gate_requirements needs a parsed BRD"
        raise ValueError(msg)

    answered_by_req = {
        q.requirement_id: state.answers[q.id]
        for q in state.questions
        if q.id in state.answers and state.answers[q.id].strip()
    }

    requirements: list[Requirement] = []
    blocked: list[str] = []
    for req in parsed.requirements:
        text = req.text
        if req.id in answered_by_req:
            text = f"{req.text} [{_CLEARING_MARKER} {answered_by_req[req.id]}]"
            req = req.model_copy(update={"text": text})
        score, issues = rule_score(req)
        # The answer clears the asked-for content gaps ONLY if it survives the gate
        # itself (_answer_clears); otherwise the item stays blocked and the open
        # question is re-asked. The answer text stays appended for estimation.
        if req.id in answered_by_req and _answer_clears(answered_by_req[req.id]):
            issues = tuple(i for i in issues if not i.startswith(("vague-terms", "undefined")))
            score = min(score, GATE_THRESHOLD - 0.05)
        if client is not None:
            try:
                llm = await llm_score(
                    client, req.model_copy(update={"text": redact_anchors(req.text)})
                )
                if llm[0] + 0.3 < score:
                    # A far-lower LLM score on a rule-flagged item is exactly what a
                    # prompt-injected "score me 0" produces — surface it, never hide it.
                    logger.warning(
                        "llm gate score %.2f far below rule %.2f for %s",
                        llm[0],
                        score,
                        req.id,
                    )
                    issues = (*issues, "llm-gate-divergence")
                score, issues = blend((score, issues), llm)
            except GatewayError as exc:
                logger.warning("llm gate scoring degraded to rules: %s", exc)
        req = req.model_copy(update={"ambiguity_score": score, "ambiguity_issues": issues})
        requirements.append(req)
        if score >= GATE_THRESHOLD:
            blocked.append(req.id)

    return state.model_copy(
        update={
            "requirements": tuple(requirements),
            "blocked_ids": tuple(blocked),
            "status": "gated",
        }
    )


def _template_question(req: Requirement) -> tuple[str, str]:
    """Deterministic fallback: issue-slug-driven Turkish question."""
    issues = ", ".join(req.ambiguity_issues) or "belirsizlik"
    lowered = tr_lower(req.text)
    if any(slug.startswith("undefined-condition") for slug in req.ambiguity_issues):
        question = (
            "Bu gereksinimde açık bırakılan koşulun sonucunu (beklenen sistem davranışını) "
            "netleştirebilir misiniz?"
        )
    elif "missing-acceptance-criteria" in req.ambiguity_issues:
        question = (
            "Bu gereksinimin kabul kriterini (hangi koşullar sağlanınca tamamlanmış "
            "sayılacağını) paylaşabilir misiniz?"
        )
    elif any(slug.startswith("vague-terms") for slug in req.ambiguity_issues):
        question = (
            "Gereksinimdeki koşullu/muğlak ifadenin kapsamını ve geçerli olduğu durumları "
            "netleştirebilir misiniz?"
        )
    elif "entegrasyon" in lowered or "sistem" in lowered:
        question = (
            "Entegrasyon için karşı sistemin sunduğu arayüzü ve veri sözleşmesinin sahibini "
            "paylaşabilir misiniz?"
        )
    else:
        question = (
            "Bu talebin kapsamını ve beklenen sonucunu ölçülebilir şekilde netleştirebilir misiniz?"
        )
    return question, f"Tespit edilen açıklar: {issues}"


async def generate_questions(
    state: PipelineState, client: GatewayClient | None = None
) -> PipelineState:
    """One clarification question per blocked requirement (existing ones are kept)."""
    prompt = load_prompt("questions")
    existing = {q.requirement_id: q for q in state.questions}
    by_id = {r.id: r for r in state.requirements}
    questions: list[ClarificationQuestion] = list(state.questions)

    for req_id in state.blocked_ids:
        if req_id in existing:
            continue
        req = by_id[req_id]
        question_text, reason = _template_question(req)
        if client is not None:
            try:
                result = await client.complete(
                    "questions",
                    [
                        {"role": "system", "content": DATA_SYSTEM},
                        {
                            "role": "user",
                            "content": (
                                f"{prompt.text}\nIssue slugs: "
                                f"{', '.join(req.ambiguity_issues) or 'unspecified'}\n"
                                f"Requirement:\n{fence(redact_anchors(req.text))}"
                            ),
                        },
                    ],
                    temperature=0.2,
                    max_tokens=300,
                )
                payload = json.loads(result.text)
                candidate = str(payload.get("question", "")).strip()
                if candidate.endswith("?") and len(candidate) > 20:
                    question_text = candidate
                    reason = str(payload.get("reason", reason)).strip() or reason
            except (GatewayError, json.JSONDecodeError, TypeError) as exc:
                logger.warning("question generation degraded to template: %s", exc)
        questions.append(
            ClarificationQuestion(
                id=f"Q-{req_id}",
                requirement_id=req_id,
                question=question_text,
                reason=reason,
            )
        )

    status = "awaiting_answers" if state.blocked_ids else "gated"
    return state.model_copy(
        update={
            "questions": tuple(questions),
            "status": status,
            "prompt_ids": {**state.prompt_ids, prompt.name: prompt.id},
        }
    )


async def decompose(state: PipelineState, client: GatewayClient | None = None) -> PipelineState:
    """Work items for CLEAR requirements only — blocked ones never enter estimation."""
    prompt = load_prompt("decompose")
    blocked = set(state.blocked_ids)
    items: list[WorkItem] = []
    unmapped: list[str] = []
    brd_ref = state.parsed.brd_ref if state.parsed else state.source_path

    for req in state.requirements:
        if req.id in blocked:
            continue
        modules = modules_for(req.text)
        title = (req.text.split(".")[0].strip() or req.text.strip() or req.text)[:120]
        if client is not None:
            try:
                result = await client.complete(
                    "decompose",
                    [
                        {"role": "system", "content": DATA_SYSTEM},
                        {
                            "role": "user",
                            "content": (
                                f"{prompt.text}\nRequirement:\n"
                                f"{fence(redact_anchors(req.text))}\n"
                                f"Draft title: {title}\nModules: {list(modules)}"
                            ),
                        },
                    ],
                    temperature=0.2,
                    max_tokens=200,
                )
                payload = json.loads(result.text)
                candidate = str(payload.get("title", "")).strip()
                if 5 < len(candidate) <= 120:
                    title = candidate
                extra = [
                    m
                    for m in payload.get("extra_modules", [])
                    if isinstance(m, str) and m in _allowed_modules() and m not in modules
                ]
                modules = modules + tuple(extra)
            except (GatewayError, json.JSONDecodeError, TypeError) as exc:
                logger.warning("decomposition refinement degraded: %s", exc)
        if not modules:
            unmapped.append(req.id)
        items.append(
            WorkItem(
                id=f"WI-{req.id.removeprefix('REQ-')}",
                brd_ref=brd_ref,
                title=title,
                description=req.text,
                requirement_ids=(req.id,),
                module_tags=modules,
                anchors=req.anchors,
            )
        )

    return state.model_copy(
        update={
            "work_items": tuple(items),
            "unmapped_ids": tuple(unmapped),
            "status": "ready_for_estimation" if not state.blocked_ids else "awaiting_answers",
            "prompt_ids": {**state.prompt_ids, prompt.name: prompt.id},
        }
    )


def _allowed_modules() -> frozenset[str]:
    from estimo_pipeline.taxonomy import AURORA_MODULES

    return AURORA_MODULES
