"""The estimator: pipeline state + ledger (+ optional code graph, gateway) → BoE draft.

Evidence discipline is structural: every line carries ledger:// analog references, plus
repo:// impact evidence and answer:// references when available — an evidence-less
EstimateLine cannot even be constructed (core model, PRINCIPLES #2). Items without
usable analogs are NOT estimated with invented numbers: they get a needs-expert line
flag via LOW confidence, a discovery risk, and the widest prior band only when the
maintainer explicitly allows fallback.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence

from estimo_code import CodeGraph
from estimo_knowledge import AnalogyCard, find_analogs
from estimo_parse import DATA_SYSTEM, fence, redact_anchors
from estimo_pipeline import PipelineState
from estimo_pipeline.prompts import Prompt
from sqlalchemy.ext.asyncio import AsyncSession

from estimo_core import (
    AssumptionRisk,
    BoeDocument,
    ConeStage,
    Confidence,
    DisciplineRange,
    EstimateLine,
    EvidenceRef,
    ImpactAnalysis,
    ThreePoint,
)
from estimo_estimate.bands import BandResult, band_from_analogs
from estimo_estimate.calibration import (
    DisciplineHistory,
    ErrorDistribution,
    discipline_history,
    historical_ratio,
    transfer_distribution,
)
from estimo_estimate.impact_worker import analyze_impact
from estimo_estimate.prompts import load_estimate_prompt
from estimo_gateway import GatewayClient, GatewayError

logger = logging.getLogger("estimo.estimate")


async def _analogs_for(
    session: AsyncSession,
    query: str,
    *,
    client: GatewayClient | None,
    limit: int,
) -> tuple[list[AnalogyCard], bool]:
    """Analog retrieval that degrades instead of failing the whole draft.

    The dense leg calls the gateway to embed the query, so an unreachable endpoint
    used to raise straight out of `estimate_state` — a temporarily-down model turned
    "your bands are computed from a narrower analog set" into "the estimate cannot be
    built at all". The lexical leg is a plain SQL query and always answers; the ledger
    screen learned the same lesson and takes the same fallback.

    Returns (cards, degraded). The flag is not decoration: a different analog set is
    a DIFFERENT BAND — measured at up to ±26% on `likely` for the same BRD, ledger and
    calibration — so a draft built this way has to say so on its face, or the document
    claims a grounding it did not have.
    """
    try:
        return await find_analogs(session, query, client=client, limit=limit), False
    except GatewayError:
        logger.warning("analog retrieval fell back to the lexical leg", exc_info=True)
        return await find_analogs(session, query, limit=limit), True


async def _llm_adjust_likely(
    client: GatewayClient,
    prompt: Prompt,
    item_text: str,
    band: BandResult,
) -> tuple[float, str | None]:
    """LLM may nudge likely WITHIN the band; anything else degrades to the draft."""
    try:
        result = await client.complete(
            "estimate",
            [
                {"role": "system", "content": DATA_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"{prompt.text}\nBand: optimistic={band.range.optimistic} "
                        f"likely={band.range.likely} pessimistic={band.range.pessimistic}\n"
                        f"Work item:\n{fence(redact_anchors(item_text))}"
                    ),
                },
            ],
            temperature=0.0,
            max_tokens=200,
        )
        payload = json.loads(result.text)
        if not isinstance(payload, dict):
            raise TypeError("expected JSON object")
        likely = float(payload["likely"])
        rationale = str(payload.get("rationale", "")).strip() or None
        if band.range.optimistic <= likely <= band.range.pessimistic:
            return round(likely, 1), rationale
        logger.warning("llm likely %.1f outside band — draft kept", likely)
    except (GatewayError, json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
        logger.warning("estimate refinement degraded: %s", exc)
    return band.range.likely, None


def _scaled(range_: ThreePoint, share: float) -> ThreePoint:
    return ThreePoint(
        optimistic=round(range_.optimistic * share, 2),
        likely=round(range_.likely * share, 2),
        pessimistic=round(range_.pessimistic * share, 2),
    )


def _discipline_split(
    final_range: ThreePoint,
    analysis: ImpactAnalysis | None,
    history: DisciplineHistory,
    module_tags: tuple[str, ...],
) -> tuple[DisciplineRange, ...]:
    """FE/BE sub-ranges for one line (S13-3).

    Precedence: the impact worker's cited proposal, then the tenant's own
    historical ratio per module (the naive baseline), then NOTHING — an unsplit
    line is the honest answer when neither the model nor the history has a basis.
    Sub-ranges scale the line's final band; they never invent their own numbers.
    """
    shares: dict[str, float] | None = None
    basis: str = "model-proposed"
    if analysis is not None and analysis.composition:
        shares = {part.discipline: part.share for part in analysis.composition}
    else:
        shares = historical_ratio(history, module_tags)
        basis = "historical-ratio"
    if not shares:
        return ()
    return tuple(
        DisciplineRange(
            discipline=discipline,
            range=_scaled(final_range, share),
            basis=basis,
            calibrated=history.calibrated(discipline),
        )
        for discipline, share in sorted(shares.items())
        if share > 0
    )


def _cone_stage(state: PipelineState) -> ConeStage:
    reqs = state.requirements
    if not reqs:
        return ConeStage.CONCEPT
    if any(r.extraction == "heuristic" for r in reqs) or state.blocked_ids:
        return ConeStage.CONCEPT
    if all(r.acceptance_criteria for r in reqs):
        return ConeStage.APPROVED_SCOPE
    return ConeStage.CONCEPT


async def estimate_state(
    session: AsyncSession,
    state: PipelineState,
    *,
    graph: CodeGraph | None = None,
    graphs: Sequence[CodeGraph] = (),
    client: GatewayClient | None = None,
    acl_keys: Sequence[str] | None = None,
    analog_limit: int = 5,
) -> BoeDocument:
    if state.status != "ready_for_estimation":
        msg = (
            f"state is {state.status!r}; only 'ready_for_estimation' states are estimated "
            "(PRINCIPLES #3 — open questions first)"
        )
        raise ValueError(msg)

    prompt = load_estimate_prompt()
    distribution: ErrorDistribution = await transfer_distribution(session)
    history: DisciplineHistory = await discipline_history(session)
    answered = {q.requirement_id: q for q in state.questions if q.id in state.answers}
    # `graph` is the CLI's local --repo build; `graphs` are the persisted per-repo
    # graphs the deployed path loads. The worker sees them as one estate (S13-2).
    all_graphs: list[CodeGraph] = [*graphs, *([graph] if graph is not None else [])]

    lines: list[EstimateLine] = []
    analyses: list[ImpactAnalysis] = []
    global_assumptions: list[AssumptionRisk] = []
    global_risks: list[AssumptionRisk] = []
    # True once any work item's analog search lost its dense leg to an unreachable
    # gateway. Recorded on the document, because the alternative is a BoE whose bands
    # came from a narrower reference class than the one it appears to claim.
    degraded_retrieval = False

    if distribution.prior_based:
        global_assumptions.append(
            AssumptionRisk(
                kind="assumption",
                text=(
                    "Bant genişlikleri kurum tarihçesi yetersiz olduğu için literatür "
                    f"öncüllerine dayanır (örnek sayısı: {distribution.samples})."
                ),
            )
        )

    for item in state.work_items:
        # Redact at query construction: every downstream boundary (embed, lexical
        # FTS, impact keywords, chat) must see quarantined text (PRINCIPLES #5).
        query = redact_anchors(f"{item.title} {item.description or ''}")
        analogs, retrieval_degraded = await _analogs_for(
            session, query, client=client, limit=analog_limit
        )
        degraded_retrieval = degraded_retrieval or retrieval_degraded
        band = band_from_analogs(analogs, distribution)

        evidence: list[EvidenceRef] = [
            EvidenceRef.from_uri(f"ledger://{card.entry_id}", label=card.item_title)
            for card in analogs[:3]
        ]
        assumptions: list[AssumptionRisk] = []
        risks: list[AssumptionRisk] = []
        analysis: ImpactAnalysis | None = None

        if all_graphs or client is not None:
            # Scope reasoning is the model's job now (ADR-0009): a tool-using loop
            # over the repo graphs, the knowledge index and the analog ledger, with
            # every claim's evidence verified before it is kept. Without a client
            # (or on any malformed/unreachable turn) this IS the old deterministic
            # graph heuristic, boxed as an analysis.
            analysis = await analyze_impact(
                session, item, query, all_graphs, client=client, acl_keys=acl_keys
            )
            analyses.append(analysis)
            for claim in analysis.modules[:4]:
                evidence.extend(claim.evidence[:2])
            for claim in analysis.integration_points[:2]:
                evidence.extend(claim.evidence[:1])
            for claim in analysis.discovery_risks:
                risks.append(
                    AssumptionRisk(
                        kind="risk",
                        text=(
                            f"Keşif riski ({claim.module or 'genel'}): {claim.text} "
                            "— teknik keşif önerilir."
                        ),
                        contingency_pd=round((band.range.likely if band else 1.0) * 0.3, 1),
                    )
                )

        for req_id in item.requirement_ids:
            if req_id in answered:
                question = answered[req_id]
                evidence.append(
                    EvidenceRef.from_uri(f"answer://{question.id}", label="müşteri cevabı")
                )
                assumptions.append(
                    AssumptionRisk(
                        kind="assumption",
                        text=f"Müşteri cevabı esas alındı: {state.answers[question.id][:200]}",
                    )
                )

        # The analog top-3 and the worker's ledger citations can name the same row;
        # a line that lists one reference twice reads as more grounded than it is.
        seen_uris: set[str] = set()
        deduped: list[EvidenceRef] = []
        for ref in evidence:
            if ref.uri not in seen_uris:
                seen_uris.add(ref.uri)
                deduped.append(ref)
        evidence = deduped

        if band is None:
            # No usable analogs: never invent a number silently (PRINCIPLES #7 spirit).
            prior_band = ThreePoint(optimistic=1.0, likely=3.0, pessimistic=8.0)
            lines.append(
                EstimateLine(
                    work_item_id=item.id,
                    range=prior_band,
                    disciplines=_discipline_split(prior_band, analysis, history, item.module_tags),
                    confidence=Confidence.LOW,
                    evidence=tuple(evidence)
                    or (
                        EvidenceRef.from_uri(
                            "note://no-analogs", label="analog bulunamadı — literatür öncülü"
                        ),
                    ),
                    assumptions=tuple(assumptions),
                    risks=(
                        *risks,
                        AssumptionRisk(
                            kind="risk",
                            text=(
                                "Defterde benzer iş bulunamadı; bant geniş literatür "
                                "öncülüdür — uzman değerlendirmesi şarttır."
                            ),
                            contingency_pd=4.0,
                        ),
                    ),
                    basis_note="no-analog prior band",
                )
            )
            continue

        likely = band.range.likely
        rationale: str | None = None
        if client is not None:
            likely, rationale = await _llm_adjust_likely(client, prompt, query, band)
        final_range = ThreePoint(
            optimistic=min(band.range.optimistic, likely),
            likely=likely,
            pessimistic=max(band.range.pessimistic, likely),
        )
        lines.append(
            EstimateLine(
                work_item_id=item.id,
                range=final_range,
                disciplines=_discipline_split(final_range, analysis, history, item.module_tags),
                confidence=band.confidence,
                evidence=tuple(evidence),
                assumptions=tuple(assumptions),
                risks=tuple(risks),
                basis_note=band.basis + (f"; LLM: {rationale}" if rationale else ""),
            )
        )

    if degraded_retrieval:
        global_risks.append(
            AssumptionRisk(
                kind="risk",
                text=(
                    "Bu taslak kurulurken model geçidine ulaşılamadı: analog arama "
                    "yalnız sözlük bacağıyla çalıştı, bant hesabı daha dar bir "
                    "referans kümesine dayanıyor. Geçit erişilebilir olduğunda "
                    "yeniden kurun."
                ),
            )
        )

    return BoeDocument(
        brd_ref=state.parsed.brd_ref if state.parsed else state.source_path,
        title=state.parsed.title if state.parsed else state.source_path,
        cone_stage=_cone_stage(state),
        lines=tuple(lines),
        questions=tuple(
            q.model_copy(update={"status": "applied"}) if q.id in state.answers else q
            for q in state.questions
        ),
        global_assumptions=tuple(global_assumptions),
        global_risks=tuple(global_risks),
        impact=tuple(analyses),
    )
