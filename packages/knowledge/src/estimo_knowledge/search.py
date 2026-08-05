"""Hybrid retrieval: Turkish lexical FTS + optional dense leg, fused with RRF.

Lexical leg: PostgreSQL `turkish` snowball config (verified against the pgvector
image) with `websearch_to_tsquery` + `ts_rank_cd`. Dense leg: pgvector cosine distance,
gated on matching embedding dimension per row. Fusion: reciprocal rank fusion (k=60),
the standard parameter from the RRF literature. A cross-encoder rerank slot sits after
fusion — interface reserved, wired when the deployment gateway exposes a rerank route.

ACL enforcement is a retrieval PRE-filter on `knowledge_chunks.acl_keys` (SECURITY.md);
the ledger is vendor-internal and carries no ACL.
"""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import Integer, Select, String, bindparam, cast, func, literal, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from estimo_core import tr_lower
from estimo_gateway import GatewayClient
from estimo_knowledge.db import KnowledgeChunk, LedgerEntryRow

RRF_K = 60

_TOKEN_RE = re.compile(r"[\wçğıöşüÇĞİÖŞÜ]+", re.UNICODE)

# Longest-match-first single-pass suffix strip. The turkish snowball config leaves
# derivational/possessive forms unstemmed (kampanyası→kampanyas, taksitli→taksitli),
# so query and index stems diverge; stripping the query token to a root and PREFIX
# matching (root:*) restores recall — over-stripping only broadens, and ranking + RRF
# keep precision.
_TR_SUFFIXES = (
    "larından",
    "lerinden",
    "larına",
    "lerine",
    "ları",
    "leri",
    "ların",
    "lerin",
    "lar",
    "ler",
    "ması",
    "mesi",
    "nın",
    "nin",
    "nun",
    "nün",
    "dan",
    "den",
    "tan",
    "ten",
    "sı",
    "si",
    "su",
    "sü",
    "yı",
    "yi",
    "yu",
    "yü",
    "ın",
    "in",
    "un",
    "ün",
    "lı",
    "li",
    "lu",
    "lü",
    "ma",
    "me",
    "ım",
    "im",
    "um",
    "üm",
    "ış",
    "iş",
    "uş",
    "üş",
    "da",
    "de",
    "ta",
    "te",
    "ı",
    "i",
    "u",
    "ü",
    "a",
    "e",
)
_MIN_ROOT = 4


def _root(token: str) -> str:
    """Multi-pass longest-first suffix strip (birleştirme→birleştir, üretimi→üret)."""
    root = token
    while True:
        for suffix in _TR_SUFFIXES:
            if root.endswith(suffix) and len(root) - len(suffix) >= _MIN_ROOT:
                root = root[: -len(suffix)]
                break
        else:
            return root


def _token_alternatives(text: str) -> list[str]:
    """One `to_tsquery` alternative per distinct query concept.

    The bare token is stemmed by to_tsquery itself (üretimi→üret matches the indexed
    stem exactly); the stripped root prefix covers derivational forms the snowball
    stemmer leaves apart (birleştir:* matches birleştirilmes). Tokens are \\w+ only,
    so the composed expressions are always valid tsquery syntax — raw user text never
    reaches to_tsquery.
    """
    alternatives: list[str] = []
    seen: set[str] = set()
    for token in _TOKEN_RE.findall(tr_lower(text)):
        if len(token) < 3:
            continue
        root = _root(token)
        if root in seen:
            continue
        seen.add(root)
        if root == token:
            alternatives.append(f"{token}:*")
        else:
            alternatives.append(f"({token} | {root}:*)")
    return alternatives


def _prefix_or_expr(text: str) -> str:
    """Combined OR expression; "" when no usable tokens exist (callers fall back to
    websearch_to_tsquery, which never raises on arbitrary input)."""
    return " | ".join(_token_alternatives(text))


def _relevance(model: type[LedgerEntryRow | KnowledgeChunk], query: str) -> tuple[Any, Any, Any]:
    """(match_clause, coordination_score, density_rank).

    Coordination — the number of DISTINCT query concepts a row matches — is the
    primary order: ts_rank_cd alone counts covers, so a row spamming one term ties a
    row matching every term, and equal scores decay to random-UUID order (a measured
    flake). Density ranks within equal coordination; id last for determinism.
    """
    alternatives = _token_alternatives(query)
    if not alternatives:
        tsquery = func.websearch_to_tsquery("turkish", query)
        match = model.search_tsv.op("@@")(tsquery)
        return match, literal(1), func.ts_rank_cd(model.search_tsv, tsquery)
    combined = func.to_tsquery("turkish", " | ".join(alternatives))
    coordination = sum(
        cast(model.search_tsv.op("@@")(func.to_tsquery("turkish", alt)), Integer)
        for alt in alternatives
    )
    return (
        model.search_tsv.op("@@")(combined),
        coordination,
        func.ts_rank_cd(model.search_tsv, combined),
    )


@dataclass(frozen=True)
class SearchHit:
    id: uuid.UUID
    title: str
    score: float
    source: Literal["ledger", "chunk"]


def rrf_merge(rankings: list[list[uuid.UUID]], k: int = RRF_K) -> list[tuple[uuid.UUID, float]]:
    """Reciprocal rank fusion; deterministic (score desc, then id) ordering."""
    scores: dict[uuid.UUID, float] = {}
    for ranking in rankings:
        for rank, item_id in enumerate(ranking, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], str(pair[0])))


def _lexical_stmt(
    model: type[LedgerEntryRow | KnowledgeChunk], query: str, limit: int
) -> Select[tuple[uuid.UUID]]:
    match, coordination, density = _relevance(model, query)
    return (
        select(model.id)
        .where(match)
        .order_by(coordination.desc(), density.desc(), model.id)
        .limit(limit)
    )


def ledger_slice_conditions(
    team: str | None, domain: str | None, discipline: str | None = None
) -> list[Any]:
    """Slice predicates shared by BOTH retrieval legs.

    Filtering after retrieval would silently shrink the result set — a reader who
    filters by team would see three matches where the ledger holds forty, because
    the top-N was chosen before the filter was known. So the slice goes into the
    SQL of each leg and the top-N is the top-N *of the slice*.

    Team, domain and discipline are stored normalized (`tr_lower` at the import
    boundary), so the comparison normalizes too. Any new slice key belongs HERE,
    not at a call site — that is the invariant that keeps every leg agreeing.
    """
    conditions: list[Any] = []
    if team:
        conditions.append(LedgerEntryRow.team == tr_lower(team.strip()))
    if domain:
        conditions.append(
            LedgerEntryRow.domain_tags.op("&&")(
                bindparam("domain_slice", [tr_lower(domain.strip())], type_=ARRAY(String(60)))
            )
        )
    if discipline:
        conditions.append(LedgerEntryRow.discipline == tr_lower(discipline.strip()))
    return conditions


async def lexical_ledger_ids(
    session: AsyncSession,
    query: str,
    *,
    limit: int = 20,
    conditions: list[Any] | None = None,
) -> list[uuid.UUID]:
    stmt = _lexical_stmt(LedgerEntryRow, query, limit)
    if conditions:
        stmt = stmt.where(*conditions)
    result = await session.execute(stmt)
    return list(result.scalars())


async def lexical_chunk_ids(
    session: AsyncSession,
    query: str,
    *,
    acl_keys: list[str],
    limit: int = 20,
) -> list[uuid.UUID]:
    match, coordination, density = _relevance(KnowledgeChunk, query)
    stmt = (
        select(KnowledgeChunk.id)
        .where(
            match,
            # ACL PRE-filter: the row must share at least one key with the caller.
            KnowledgeChunk.acl_keys.op("&&")(bindparam("acl", acl_keys, type_=ARRAY(String(80)))),
        )
        # Authority breaks relevance ties (S9-5): canonical (0.95) > generated code
        # wikis (0.7) > raw source chunks (0.5). Relevance stays primary.
        .order_by(
            coordination.desc(), density.desc(), KnowledgeChunk.authority.desc(), KnowledgeChunk.id
        )
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars())


async def dense_ledger_matches(
    session: AsyncSession,
    embedding: list[float],
    *,
    limit: int = 20,
    conditions: list[Any] | None = None,
) -> list[tuple[uuid.UUID, float]]:
    """Nearest ledger entries WITH their cosine similarity.

    The similarity is the only defensible "how alike is this?" number the system
    has: it is measured between two vectors. The fused RRF score is not — it is
    built from ordinal positions, so 1/(60+1) means "first", not "97% alike", and
    rendering it as a percentage would invent a measurement. Anything that wants
    to show a percentage must read it from here, and show nothing when the dense
    leg did not run.
    """
    distance = LedgerEntryRow.embedding.cosine_distance(embedding)
    stmt = (
        select(LedgerEntryRow.id, distance)
        .where(
            LedgerEntryRow.embedding.is_not(None),
            LedgerEntryRow.embedding_dim == len(embedding),
            *(conditions or ()),
        )
        .order_by(distance, LedgerEntryRow.id)
        .limit(limit)
    )
    result = await session.execute(stmt)
    # pgvector cosine distance is 1 - cosine similarity, in [0, 2]; negative
    # similarity means "points the other way", which is no similarity at all.
    #
    # NaN is dropped, not clamped. A zero-vector embedding (a misbehaving embedder,
    # a hand-backfilled row) makes cosine distance undefined, and pgvector returns
    # NaN for it — and a clamp fails OPEN on NaN, because `nan < 1.0` is False, so
    # `min(1.0, nan)` returns 1.0 and the least comparable row in the ledger would
    # wear a "100% match" chip. An unmeasurable distance is not a similarity of any
    # value. Such a row leaves the DENSE ranking (Postgres sorts NaN last, so it was
    # never a near neighbour anyway) and can still be found by the lexical leg.
    return [
        (row_id, max(0.0, min(1.0, 1.0 - value)))
        for row_id, dist in result
        if not math.isnan(value := float(dist))
    ]


async def dense_ledger_ids(
    session: AsyncSession,
    embedding: list[float],
    *,
    limit: int = 20,
    conditions: list[Any] | None = None,
) -> list[uuid.UUID]:
    matches = await dense_ledger_matches(session, embedding, limit=limit, conditions=conditions)
    return [row_id for row_id, _ in matches]


async def dense_chunk_ids(
    session: AsyncSession,
    embedding: list[float],
    *,
    acl_keys: list[str],
    limit: int = 20,
) -> list[uuid.UUID]:
    """Nearest chunks by vector distance, behind the SAME ACL pre-filter as the
    lexical leg.

    The pre-filter is not optional here and not a copy-paste of the lexical one for
    tidiness: a dense leg without it would be a complete ACL bypass reachable by anyone
    who can phrase a query, since vector similarity has no notion of permission.
    SECURITY.md requires the filter at query time, on every path that returns rows.

    `embedding_dim` is matched so a corpus embedded by a previous model drops out
    rather than being scored in the wrong vector space.
    """
    stmt = (
        select(KnowledgeChunk.id)
        .where(
            KnowledgeChunk.embedding.is_not(None),
            KnowledgeChunk.embedding_dim == len(embedding),
            KnowledgeChunk.acl_keys.op("&&")(bindparam("acl", acl_keys, type_=ARRAY(String(80)))),
        )
        .order_by(KnowledgeChunk.embedding.cosine_distance(embedding), KnowledgeChunk.id)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars())


async def hybrid_chunk_ids(
    session: AsyncSession,
    query: str,
    *,
    acl_keys: list[str],
    client: GatewayClient | None = None,
    limit: int = 20,
) -> list[uuid.UUID]:
    """Lexical always; the dense leg joins in when a gateway client is provided.

    Until this existed the chunk shelf had no dense path at all, so the embedding
    writer filled `knowledge_chunks.embedding` for a column no query read — cost with
    no retrieval benefit. The ledger shelf had both legs; this brings the wiki and
    code shelves to parity.
    """
    rankings = [await lexical_chunk_ids(session, query, acl_keys=acl_keys, limit=limit * 2)]
    if client is not None:
        embedded = await client.embed([query])
        rankings.append(
            await dense_chunk_ids(session, embedded.vectors[0], acl_keys=acl_keys, limit=limit * 2)
        )
    return [chunk_id for chunk_id, _ in rrf_merge(rankings)][:limit]


async def hybrid_ledger_matches(
    session: AsyncSession,
    query: str,
    *,
    client: GatewayClient | None = None,
    limit: int = 10,
    team: str | None = None,
    domain: str | None = None,
    discipline: str | None = None,
) -> list[tuple[uuid.UUID, float | None]]:
    """Lexical always; dense joins in when a gateway client is provided.

    Each hit carries its MEASURED cosine similarity, or `None` when the dense leg
    did not run (or the entry has no embedding of the right dimension) — the rank
    alone never becomes a number.
    """
    conditions = ledger_slice_conditions(team, domain, discipline)
    rankings = [await lexical_ledger_ids(session, query, limit=limit * 2, conditions=conditions)]
    similarity: dict[uuid.UUID, float] = {}
    if client is not None:
        embedded = await client.embed([query])
        dense = await dense_ledger_matches(
            session, embedded.vectors[0], limit=limit * 2, conditions=conditions
        )
        rankings.append([row_id for row_id, _ in dense])
        similarity = dict(dense)
    fused = [item_id for item_id, _ in rrf_merge(rankings)][:limit]
    return [(item_id, similarity.get(item_id)) for item_id in fused]


async def hybrid_ledger_ids(
    session: AsyncSession,
    query: str,
    *,
    client: GatewayClient | None = None,
    limit: int = 10,
    team: str | None = None,
    domain: str | None = None,
    discipline: str | None = None,
) -> list[uuid.UUID]:
    matches = await hybrid_ledger_matches(
        session,
        query,
        client=client,
        limit=limit,
        team=team,
        domain=domain,
        discipline=discipline,
    )
    return [item_id for item_id, _ in matches]
