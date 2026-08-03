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


async def approve(session: AsyncSession, page: CanonicalPage, *, approver: str) -> CanonicalPage:
    """Human gate: version-bump, mark approved, publish into retrieval."""
    if page.status == "approved":
        return page
    page.status = "approved"
    page.version += 1
    page.approved_by = approver
    await session.flush()
    # updated_at is server-generated; refresh before reading it (an expired-attribute
    # access would attempt sync IO inside the async session).
    await session.refresh(page)
    await upsert_document(
        session,
        source_type="canonical",
        source_ref=f"canonical://{page.topic}@{page.version}",
        title=page.title,
        text=page.body,
        acl_keys=["public"],
        freshness_at=page.updated_at,
        authority=CANONICAL_AUTHORITY,
    )
    return page
