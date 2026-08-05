"""Impact Map (S12-4): where the work lands, with the evidence beside it.

The design draws a module graph and a docked evidence panel. Two constraints shape
what this endpoint may serve:

- **It runs BEFORE the desk**, so it must not touch the BoE draft. Evidence here is
  what grounds the mapping — wiki pages and analog jobs retrieved for the module —
  never a band, never anything derived from one (PRINCIPLES #4).
- **Retrieval is permission-aware**, so the wiki leg carries the caller's own ACL
  audiences through the same pre-filter every other surface uses. A map that showed
  a restricted page's title would leak it just as surely as showing its text.

Edges are derived, not invented: two modules are linked when a work item touches
both. An edge that only ONE work item supports is marked uncertain — the design
draws it dashed — because a single co-occurrence is as likely to be incidental as
structural.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from typing import Annotated, Any

from estimo_knowledge import find_analogs, is_stale
from estimo_knowledge.db import KnowledgeChunk
from estimo_knowledge.search import lexical_chunk_ids
from estimo_parse.anchors import redact_anchors
from estimo_pipeline import PipelineState
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimo_api.auth import Principal, clamp_acl_keys, current_principal
from estimo_api.db import get_session
from estimo_api.estimates_models import EstimateRecord

router = APIRouter(prefix="/v1/estimates", tags=["estimates"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# Wiki hits and analog jobs shown per module. Small on purpose: the panel is for
# deciding whether the mapping is trustworthy, not for reading the wiki.
EVIDENCE_LIMIT = 4

# Bucket for work items the decomposer attributed to no module.
UNMAPPED = "(unmapped)"


def _confidence(wiki_hits: int, analog_hits: int, work_items: int) -> str:
    """How well EVIDENCE covers this module.

    Safe ONLY while no draft exists — see `_draft_makes_coverage_invertible`. This
    started life as "coverage, not a band, therefore always safe", which was wrong:
    the estimator BRANCHES on the same analog lookup, so once a draft exists the
    coverage IS the branch predicate.
    """
    if wiki_hits == 0 and analog_hits == 0:
        return "low"
    if wiki_hits and analog_hits and work_items > 1:
        return "high"
    return "medium"


@router.get("/{estimate_id}/impact")
async def impact_map(
    estimate_id: uuid.UUID,
    session: SessionDep,
    principal: Annotated[Principal, Depends(current_principal)],
    module: Annotated[str | None, Query(max_length=120)] = None,
) -> dict[str, Any]:
    """Modules, their links, and — for `module` — the evidence behind the mapping."""
    record = await session.get(EstimateRecord, estimate_id)
    if record is None:
        raise HTTPException(status_code=404, detail="estimate not found")
    state = PipelineState.model_validate(record.state)

    counts: Counter[str] = Counter()
    requirements: defaultdict[str, set[str]] = defaultdict(set)
    items_for: defaultdict[str, list[str]] = defaultdict(list)
    edges: Counter[tuple[str, str]] = Counter()
    for item in state.work_items:
        # A work item the decomposer could not attribute is the most interesting one
        # on this screen, not the least: dropping it made the map claim the BRD lands
        # only where mapping succeeded.
        tags = sorted(set(item.module_tags)) or [UNMAPPED]
        for tag in tags:
            counts[tag] += 1
            requirements[tag].update(item.requirement_ids)
            items_for[tag].append(item.title)
        for left_index, left in enumerate(tags):
            for right in tags[left_index + 1 :]:
                edges[(left, right)] += 1

    # Once a draft exists, coverage stops being a neutral fact about retrieval and
    # becomes a readout of the closed draft: the estimator takes its no-analog branch
    # exactly when this lookup comes back empty, pinning that line at a constant band
    # with LOW confidence and a fixed contingency. A reader on this screen — which
    # runs one step BEFORE the desk and has no independent-first gate — could then
    # infer the band before recording their own, which is precisely the leak the desk
    # closed in S12-1a. Before a draft exists there is no band to infer, so the signal
    # is served in full; afterwards it is withheld until the estimator's own gate has
    # already opened. Closing this for good needs a prior band that is not a constant
    # (ROADMAP S12-1a), not a different threshold here.
    hide_coverage = record.boe is not None

    acl_keys = clamp_acl_keys(principal, None)
    modules: list[dict[str, Any]] = []
    for name, work_items in counts.most_common():
        # Skip the retrieval entirely when its result cannot be shown: the overview
        # used to run two retrieval passes per module and discard both.
        wiki, analogs = (
            ([], [])
            if hide_coverage
            else await _evidence(session, _query_for(name, items_for), acl_keys, brief=True)
        )
        modules.append(
            {
                "module": name,
                "work_items": work_items,
                "requirement_ids": sorted(requirements[name]),
                "titles": items_for[name][:3],
                "wiki_hits": None if hide_coverage else len(wiki),
                "analog_hits": None if hide_coverage else len(analogs),
                "confidence": (
                    None if hide_coverage else _confidence(len(wiki), len(analogs), work_items)
                ),
            }
        )

    selected: dict[str, Any] | None = None
    if module:
        if module not in counts:
            raise HTTPException(status_code=404, detail="module not in this estimate")
        wiki, analogs = await _evidence(
            session, _query_for(module, items_for), acl_keys, brief=False
        )
        selected = {
            "module": module,
            "requirement_ids": sorted(requirements[module]),
            "wiki": wiki,
            "analogs": analogs,
            # Verified repo:// citations from the draft's impact analyses (S13-2) —
            # the code references S12-4 shipped without. Present only once a draft
            # exists; they are placement evidence, not bands, so the coverage gate
            # above does not apply to them.
            "code": _code_refs(record.boe, module),
        }

    return {
        "modules": modules,
        "edges": [
            {"source": left, "target": right, "weight": weight, "uncertain": weight < 2}
            for (left, right), weight in edges.most_common()
        ],
        "selected": selected,
    }


def _code_refs(boe: dict[str, Any] | None, module: str) -> list[dict[str, Any]]:
    """repo:// evidence the draft's impact analyses attached to this module.

    Read straight off the stored document — these URIs were verified against the
    loaded graphs when the analysis was built, so this is a projection, not a new
    retrieval (and therefore needs no ACL leg: the reader is already allowed to see
    the estimate the analyses belong to)."""
    if not boe:
        return []
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for analysis in boe.get("impact", []) or []:
        for claim in analysis.get("modules", []) or []:
            if claim.get("module") != module:
                continue
            for ref in claim.get("evidence", []) or []:
                uri = str(ref.get("uri", ""))
                if not uri.startswith("repo://") or uri in seen:
                    continue
                seen.add(uri)
                refs.append({"uri": uri, "claim": claim.get("text", "")})
    return refs[:EVIDENCE_LIMIT]


def _query_for(module: str, items_for: dict[str, list[str]]) -> str:
    """What to retrieve evidence WITH.

    The module name alone is a poor query: a ledger row reads "Taksitli fatura
    ekranı", not "billing-core", so searching by tag matched almost nothing and the
    panel would have shown an empty, authoritative-looking result. The work items
    that touch the module are the actual description of the work, so they carry the
    query and the tag only seeds it.
    """
    # Titles are REDACTED first. Every other retrieval boundary does this
    # (`estimator.py` calls `redact_anchors` before building its query) because a
    # work-item title inherits its requirement's first sentence verbatim — budget and
    # date anchors included. Ranking is coordination-first, so each anchor token is a
    # whole extra concept: unredacted, the customer's stated budget would decide
    # which analogs a reader sees, which is PRINCIPLES #5 inverted.
    titles = [redact_anchors(title) for title in items_for.get(module, [])[:5]]
    return " ".join([module.replace("-", " "), *titles])


async def _evidence(
    session: AsyncSession, query: str, acl_keys: list[str], *, brief: bool
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Wiki pages and analog jobs retrieved for one module.

    The wiki leg goes through the SAME ACL pre-filter as every other retrieval path:
    a title is content, and a map that listed a restricted page would leak it.
    """
    chunk_ids = await lexical_chunk_ids(session, query, acl_keys=acl_keys, limit=EVIDENCE_LIMIT)
    wiki: list[dict[str, Any]] = []
    if chunk_ids:
        rows = (
            (await session.execute(select(KnowledgeChunk).where(KnowledgeChunk.id.in_(chunk_ids))))
            .scalars()
            .all()
        )
        by_id = {row.id: row for row in rows}
        for chunk_id in chunk_ids:
            chunk = by_id.get(chunk_id)
            if chunk is None:
                continue
            wiki.append(
                {
                    "title": chunk.title or chunk.source_ref,
                    # The panel splits by SOURCE: a code-wiki chunk is repository
                    # evidence and belongs under code references, not under Wiki.
                    "source_type": chunk.source_type,
                    "stale": is_stale(chunk.freshness_at),
                    "freshness_at": (
                        chunk.freshness_at.isoformat() if chunk.freshness_at else None
                    ),
                    # The snippet is the point of the panel: a title alone cannot tell
                    # a reader whether the mapping is grounded.
                    "snippet": None if brief else chunk.text[:240],
                }
            )

    cards = await find_analogs(session, query, limit=EVIDENCE_LIMIT)
    analogs = [
        {
            "brd_ref": card.brd_ref,
            "item_title": card.item_title,
            "estimate": card.estimate.model_dump(mode="json") if card.estimate else None,
            "actual_effort": card.actual_effort,
            "scope_changed": card.scope_changed,
            "rank": card.rank,
        }
        for card in cards
    ]
    return wiki, analogs
