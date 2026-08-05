"""Agentic impact analysis per work item (S13-2, ADR-0009).

A tool-using loop over (a) every persisted repo CodeGraph, (b) the knowledge index,
(c) the analog ledger. The protocol is JSON actions over plain chat completions —
deliberately NOT provider tool-calling: it works against any OpenAI-compatible
endpoint (including gateways with no tools support), needs no gateway surgery, and
degrades to the deterministic graph heuristic on any malformed turn.

Trust boundary: the model proposes, the verifier disposes. Every claim must cite
evidence URIs; a URI is kept only when this run's tools actually returned it, or —
for repo:// — when it independently resolves inside a loaded graph (right repo,
right commit, real file, lines within the file). Claims whose evidence all fails
are dropped and counted, so a filtered analysis is visibly filtered.

The Turkish→English bridging the 14-entry `_TERM_SYNONYMS` dictionary used to do is
now the model's job (it translates domain words into identifier terms in its
search_code queries); the dictionary survives only inside `impact_for`, the
deterministic fallback.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from typing import Any

from estimo_code import CodeGraph, impact_for
from estimo_knowledge import find_analogs
from estimo_knowledge.db import KnowledgeChunk
from estimo_knowledge.search import lexical_chunk_ids
from estimo_parse import DATA_SYSTEM, fence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimo_core import (
    Confidence,
    EvidenceRef,
    ImpactAnalysis,
    ImpactClaim,
    WorkItem,
)
from estimo_estimate.prompts import load_impact_prompt
from estimo_gateway import GatewayClient, GatewayError

logger = logging.getLogger("estimo.estimate.impact")

MAX_TURNS = 6
# Two consecutive unparseable replies end the conversation — one malformed turn is
# recoverable (the model gets the parse error back), a second means this endpoint
# does not speak the protocol and the deterministic path is the honest answer.
MAX_STRIKES = 2
TOOL_RESULT_LIMIT = 8
_REPO_URI_RE = re.compile(
    r"^repo://(?P<repo>[^@]+)@(?P<commit>[^/]+)/(?P<path>[^#]+)(?:#L(?P<start>\d+)-L(?P<end>\d+))?$"
)
_TOKEN_RE = re.compile(r"[\w]+")


def _search_code(graphs: Sequence[CodeGraph], query: str) -> list[dict[str, Any]]:
    """Deterministic symbol search across every graph. No synonyms: the model
    already speaks identifier English by the time it calls this."""
    terms = {token.lower() for token in _TOKEN_RE.findall(query) if len(token) >= 3}
    hits: list[dict[str, Any]] = []
    for graph in graphs:
        for term in terms:
            for path, symbol, start, end in sorted(graph.symbol_terms.get(term, ())):
                hits.append(
                    {
                        "repo": graph.repo,
                        "module": graph.module_of.get(path, "(root)"),
                        "symbol": symbol,
                        "uri": graph.evidence_uri(path, start, end),
                    }
                )
    # Stable order, then cap: a query matching a generic term ("get") must not
    # flood the conversation with hundreds of rows.
    hits.sort(key=lambda h: (h["repo"], h["module"], h["symbol"]))
    return hits[:TOOL_RESULT_LIMIT]


async def _search_wiki(
    session: AsyncSession, query: str, acl_keys: Sequence[str] | None
) -> list[dict[str, Any]]:
    chunk_ids = await lexical_chunk_ids(
        session, query, acl_keys=list(acl_keys or []), limit=TOOL_RESULT_LIMIT
    )
    if not chunk_ids:
        return []
    rows = (
        (await session.execute(select(KnowledgeChunk).where(KnowledgeChunk.id.in_(chunk_ids))))
        .scalars()
        .all()
    )
    by_id = {row.id: row for row in rows}
    return [
        {
            "title": chunk.title or chunk.source_ref,
            "uri": chunk.source_ref,
            "source_type": chunk.source_type,
            "snippet": chunk.text[:240],
        }
        for chunk_id in chunk_ids
        if (chunk := by_id.get(chunk_id)) is not None
    ]


async def _find_analogs_tool(
    session: AsyncSession, query: str, client: GatewayClient | None
) -> list[dict[str, Any]]:
    try:
        cards = await find_analogs(session, query, client=client, limit=5)
    except GatewayError:
        # The dense leg needs an embedding; a timeout there must degrade this ONE
        # tool call to lexical, not abort the whole analysis turn.
        cards = await find_analogs(session, query, limit=5)
    return [
        {
            "uri": f"ledger://{card.entry_id}",
            "title": card.item_title,
            "modules": list(card.module_tags),
            "actual_effort": card.actual_effort,
        }
        for card in cards
    ]


def _resolves_in_graphs(uri: str, graphs: Sequence[CodeGraph]) -> bool:
    """A repo:// URI is real when a loaded graph has that repo AT that commit and
    the path/lines exist. Verification must never widen: an unknown scheme or a
    stale commit is a NO."""
    match = _REPO_URI_RE.match(uri)
    if match is None:
        return False
    for graph in graphs:
        if graph.repo != match.group("repo") or graph.commit != match.group("commit"):
            continue
        for parsed in graph.files:
            if parsed.path != match.group("path"):
                continue
            if match.group("start") is None:
                return True
            return int(match.group("end")) <= max(parsed.line_count, 1)
    return False


def _verified_claims(
    raw_claims: Any,
    seen_uris: set[str],
    graphs: Sequence[CodeGraph],
) -> tuple[list[ImpactClaim], int]:
    claims: list[ImpactClaim] = []
    dropped = 0
    if not isinstance(raw_claims, list):
        return claims, 0
    for raw in raw_claims:
        if not isinstance(raw, dict) or not str(raw.get("text", "")).strip():
            dropped += 1
            continue
        module_label = str(raw["module"])[:120] if raw.get("module") else None
        kept_refs: list[EvidenceRef] = []
        for uri in raw.get("evidence", []) or []:
            uri_text = str(uri)
            if uri_text not in seen_uris and not _resolves_in_graphs(uri_text, graphs):
                continue
            try:
                kept_refs.append(EvidenceRef.from_uri(uri_text, label=module_label))
            except ValueError:
                continue
        if kept_refs:
            module = raw.get("module")
            claims.append(
                ImpactClaim(
                    text=str(raw["text"])[:500],
                    module=str(module)[:120] if module else None,
                    evidence=tuple(kept_refs[:4]),
                )
            )
        else:
            dropped += 1
    return claims, dropped


def deterministic_analysis(
    item: WorkItem, query: str, graphs: Sequence[CodeGraph]
) -> ImpactAnalysis:
    """The pre-S13 heuristic (synonym dictionary and all), boxed as an analysis."""
    modules: list[ImpactClaim] = []
    risks: list[ImpactClaim] = []
    repos: list[str] = []
    for graph in graphs:
        impacts = impact_for(graph, query)
        if impacts:
            repos.append(graph.repo)
        for impact in impacts[:4]:
            refs = tuple(
                EvidenceRef.from_uri(uri, label=f"{impact.module} ({impact.confidence})")
                for uri in impact.evidence_uris[:2]
            )
            if not refs:
                continue
            claim = ImpactClaim(
                text=f"{impact.module}: {impact.reason}", module=impact.module, evidence=refs
            )
            if impact.discovery_suggested:
                risks.append(claim)
            else:
                modules.append(claim)
    return ImpactAnalysis(
        work_item_id=item.id,
        repos=tuple(repos),
        modules=tuple(modules),
        discovery_risks=tuple(risks),
        confidence=Confidence.MEDIUM if modules else Confidence.LOW,
        source="deterministic",
    )


def _parse_action(text: str) -> dict[str, Any] | None:
    """One JSON object, tolerating a fenced block — anything else is a strike."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-z]*\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _repo_inventory(graphs: Sequence[CodeGraph]) -> str:
    if not graphs:
        return "No repositories are indexed."
    lines = []
    for graph in graphs:
        modules = sorted(set(graph.module_of.values()))[:12]
        lines.append(f"- {graph.repo} @ {graph.commit[:12]}: modules {', '.join(modules)}")
    return "Indexed repositories:\n" + "\n".join(lines)


async def analyze_impact(
    session: AsyncSession,
    item: WorkItem,
    query: str,
    graphs: Sequence[CodeGraph],
    *,
    client: GatewayClient | None,
    acl_keys: Sequence[str] | None = None,
    max_turns: int = MAX_TURNS,
) -> ImpactAnalysis:
    """The agentic loop; every exit path lands on a valid ImpactAnalysis.

    `query` is the REDACTED work-item text — the caller quarantines anchors before
    this function, so every tool leg and every prompt sees clean text
    (PRINCIPLES #5)."""
    if client is None:
        return deterministic_analysis(item, query, graphs)

    prompt = load_impact_prompt()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": f"{DATA_SYSTEM}\n\n{prompt.text}"},
        {
            "role": "user",
            "content": f"{_repo_inventory(graphs)}\n\nWork item:\n{fence(query)}",
        },
    ]
    seen_uris: set[str] = set()
    strikes = 0

    for _ in range(max_turns):
        try:
            result = await client.complete("impact", messages, temperature=0.0, max_tokens=900)
        except GatewayError as exc:
            logger.warning("impact loop degraded to deterministic analysis: %s", exc)
            return deterministic_analysis(item, query, graphs)

        action = _parse_action(result.text)
        if action is None or "action" not in action:
            strikes += 1
            if strikes >= MAX_STRIKES:
                logger.warning("impact loop: %d unparseable turns — falling back", strikes)
                return deterministic_analysis(item, query, graphs)
            messages.append({"role": "assistant", "content": result.text})
            messages.append(
                {
                    "role": "user",
                    "content": "Reply with exactly one JSON action object, nothing else.",
                }
            )
            continue

        name = action.get("action")
        if name == "finalize":
            raw = action.get("analysis")
            if not isinstance(raw, dict):
                return deterministic_analysis(item, query, graphs)
            modules, dropped_m = _verified_claims(raw.get("modules"), seen_uris, graphs)
            integrations, dropped_i = _verified_claims(
                raw.get("integration_points"), seen_uris, graphs
            )
            risks, dropped_r = _verified_claims(raw.get("discovery_risks"), seen_uris, graphs)
            known_repos = {graph.repo for graph in graphs}
            try:
                confidence = Confidence(str(raw.get("confidence", "low")))
            except ValueError:
                confidence = Confidence.LOW
            try:
                return ImpactAnalysis(
                    work_item_id=item.id,
                    repos=tuple(
                        r
                        for r in dict.fromkeys(map(str, raw.get("repos", []) or []))
                        if r in known_repos
                    ),
                    modules=tuple(modules),
                    integration_points=tuple(integrations),
                    discovery_risks=tuple(risks),
                    composition=tuple(raw.get("composition") or []),
                    confidence=confidence,
                    source="agentic",
                    dropped_claims=dropped_m + dropped_i + dropped_r,
                )
            except ValueError:
                # A malformed composition (shares that don't sum, duplicate
                # disciplines) must not cost the whole analysis.
                return ImpactAnalysis(
                    work_item_id=item.id,
                    modules=tuple(modules),
                    integration_points=tuple(integrations),
                    discovery_risks=tuple(risks),
                    confidence=confidence,
                    source="agentic",
                    dropped_claims=dropped_m + dropped_i + dropped_r,
                )

        query_arg = str(action.get("query", ""))[:500]
        if name == "search_code":
            payload: Any = _search_code(graphs, query_arg)
        elif name == "search_wiki":
            payload = await _search_wiki(session, query_arg, acl_keys)
        elif name == "find_analogs":
            payload = await _find_analogs_tool(session, query_arg, client)
        else:
            strikes += 1
            if strikes >= MAX_STRIKES:
                return deterministic_analysis(item, query, graphs)
            messages.append({"role": "assistant", "content": result.text})
            messages.append(
                {"role": "user", "content": f"Unknown action {name!r}. Use the documented ones."}
            )
            continue

        for row in payload:
            uri = row.get("uri")
            if uri:
                seen_uris.add(str(uri))
        messages.append({"role": "assistant", "content": result.text})
        messages.append(
            {
                "role": "user",
                "content": f"Result of {name}:\n{json.dumps(payload, ensure_ascii=False)}",
            }
        )

    logger.warning("impact loop: turn budget exhausted without finalize — falling back")
    return deterministic_analysis(item, query, graphs)
