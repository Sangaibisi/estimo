"""Canonical pages curation (S9-4): candidate → HUMAN approval → versioned retrieval.

The LLM only DRAFTS candidates (distilled from existing retrieval chunks, sources
recorded); a human approves. Only approved pages enter retrieval — as the
highest-authority chunk tier (0.95), above generated code wikis (0.7) and raw source
chunks (0.5). Draft candidates never leak into retrieval.
"""

from __future__ import annotations

import logging

from estimo_knowledge import KnowledgeChunk, lexical_chunk_ids, upsert_document
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimo_connectors.db import CanonicalPage
from estimo_core import restricting_audiences
from estimo_gateway import GatewayClient, GatewayError

logger = logging.getLogger("estimo.connectors.canonical")

CANONICAL_AUTHORITY = 0.95

_DISTILL_PROMPT = """You are drafting a canonical knowledge page for an estimation \
product. Distill the source excerpts below into a single concise reference page about \
the topic. Keep only durable facts (interfaces, rules, gotchas); drop anything \
speculative. Answer in the language of the sources. Output plain text, no markdown \
headers beyond simple lines.

TOPIC: {topic}

SOURCES:
{sources}
"""


async def generate_candidate(
    session: AsyncSession,
    *,
    topic: str,
    client: GatewayClient | None = None,
    acl_keys: list[str] | None = None,
    max_sources: int = 6,
) -> CanonicalPage:
    """Create/refresh the DRAFT candidate for a topic from retrieval evidence."""
    chunk_ids = await lexical_chunk_ids(
        session, topic, acl_keys=acl_keys or ["public"], limit=max_sources
    )
    chunks = list(
        (
            await session.execute(select(KnowledgeChunk).where(KnowledgeChunk.id.in_(chunk_ids)))
        ).scalars()
    )
    source_refs = [f"{chunk.source_type}:{chunk.source_ref}" for chunk in chunks]
    excerpts = "\n---\n".join(
        f"[{chunk.title or chunk.source_ref}]\n{chunk.text[:1200]}" for chunk in chunks
    )
    body = ""
    if client is not None and excerpts:
        try:
            completion = await client.complete(
                "knowledge",
                [
                    {
                        "role": "user",
                        "content": _DISTILL_PROMPT.format(topic=topic, sources=excerpts),
                    }
                ],
                temperature=0.2,
            )
            body = completion.text
        except GatewayError as exc:
            logger.warning("distillation degraded to skeleton: %s", exc)
    if not body:
        # Deterministic skeleton — a human can still edit and approve it.
        body = f"{topic}\n\n" + "\n\n".join(
            f"- {chunk.title or chunk.source_ref}: {chunk.text[:300]}" for chunk in chunks
        )

    page = await session.scalar(select(CanonicalPage).where(CanonicalPage.topic == topic))
    if page is None:
        page = CanonicalPage(topic=topic, title=topic, body=body, source_refs=source_refs)
        session.add(page)
    elif page.status == "draft":
        page.body = body
        page.source_refs = source_refs
    else:
        # An approved page is immutable through this path; drafting a revision
        # bumps nothing until a human approves it again.
        page.status = "draft"
        page.body = body
        page.source_refs = source_refs
    await session.flush()
    return page


async def _source_chunks(session: AsyncSession, page: CanonicalPage) -> list[KnowledgeChunk]:
    refs = [ref.split(":", 1)[1] for ref in (page.source_refs or []) if ":" in ref]
    if not refs:
        return []
    result = await session.execute(
        select(KnowledgeChunk).where(KnowledgeChunk.source_ref.in_(refs))
    )
    return list(result.scalars())


async def approve(
    session: AsyncSession,
    page: CanonicalPage,
    *,
    approver: str,
    acl_keys: list[str] | None = None,
) -> CanonicalPage:
    """Human gate: version-bump, mark approved, publish into retrieval.

    ACL discipline: the page contains its sources' text, so it may only be visible
    to readers who can see EVERY source. `acl_keys` may only NARROW that audience; it
    cannot replace it. Overriding it outright (the previous behaviour) let an approver
    publish text distilled from a restricted space to a wider one, the same widening
    the pre-filter exists to prevent, just applied at write time.

    PUBLIC_ACL does not constrain the intersection, because every reader holds it —
    a page built from one public source and one `finans` source is readable by
    `finans`, not by nobody. Getting that wrong is what made the ordinary case look
    unpublishable and made an arbitrary override feel necessary. Sources with
    genuinely disjoint audiences stay unpublishable together.

    Freshness is the OLDEST source's freshness, not curation time — a page distilled
    from stale sources must still trip the staleness warning.
    """
    if page.status == "approved":
        return page

    sources = await _source_chunks(session, page)
    # The body outlives its sources. Module-wiki source_refs embed the commit SHA, so
    # ANY push to a synced repo prunes every chunk from the previous sync — a draft
    # awaiting approval can therefore lose sources between drafting and approving,
    # while its body still contains their text. Publishing to whatever audience the
    # SURVIVORS share would widen access to the text of the source that vanished.
    expected_refs = {ref.split(":", 1)[1] for ref in (page.source_refs or []) if ":" in ref}
    missing = expected_refs - {chunk.source_ref for chunk in sources}
    if missing:
        raise ValueError(
            f"{len(missing)} source chunk(s) this page was distilled from no longer "
            "exist, so the audience that may read the page cannot be determined — "
            "regenerate the draft before approving"
        )
    computed = restricting_audiences([set(chunk.acl_keys or []) for chunk in sources])
    if computed is None:
        raise ValueError(
            "sources have no common ACL audience, so no audience can read every "
            "source — remove the sources that do not share an audience, then approve"
        )
    if acl_keys is None:
        acl_keys = sorted(computed)
    else:
        narrowed = computed & set(acl_keys)
        if not narrowed:
            raise ValueError(
                f"acl_keys may only narrow the sources' common audience "
                f"{sorted(computed)}; {sorted(set(acl_keys))} shares nothing with it"
            )
        acl_keys = sorted(narrowed)
    freshness_candidates = [
        chunk.freshness_at for chunk in sources if chunk.freshness_at is not None
    ]
    freshness = min(freshness_candidates) if freshness_candidates else None

    page.status = "approved"
    page.version += 1
    page.approved_by = approver
    await session.flush()
    # A STABLE source_ref: re-approval replaces the previous version's chunk via
    # the (source_type, source_ref) upsert — superseded 0.95-authority text must
    # not accumulate in retrieval. The version lives on the page row.
    await upsert_document(
        session,
        source_type="canonical",
        source_ref=f"canonical://{page.topic}",
        title=page.title,
        text=page.body,
        acl_keys=acl_keys,
        freshness_at=freshness,
        authority=CANONICAL_AUTHORITY,
    )
    return page
