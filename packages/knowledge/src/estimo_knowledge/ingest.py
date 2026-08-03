"""Chunk ingestion glue: generated pages (e.g. S5 module wikis) → knowledge_chunks.

A database-backed upsert on the (source_type, source_ref) unique index — regenerated
pages replace their previous version atomically, so concurrent re-ingestion cannot
duplicate. Embedding columns are explicitly reset: new text invalidates old vectors.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

STALE_AFTER_DAYS = 548  # ~18 months (S9-5): older sources carry a staleness warning


def is_stale(freshness_at: dt.datetime | None, *, now: dt.datetime | None = None) -> bool:
    """A source with UNKNOWN freshness is treated as stale — honesty over optimism."""
    if freshness_at is None:
        return True
    reference = now or dt.datetime.now(dt.UTC)
    return (reference - freshness_at).days > STALE_AFTER_DAYS


from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from estimo_knowledge.db import KnowledgeChunk


async def upsert_generated_chunks(
    session: AsyncSession,
    pages: Iterable[tuple[str, str, str]],
    *,
    source_type: str = "code-wiki",
    acl_keys: list[str] | None = None,
    authority: float = 0.7,
) -> int:
    """Upsert (source_ref, title, text) pages keyed by (source_type, source_ref).

    Generated module wikis default to a higher authority than raw wiki chunks (they are
    derived from code, not prose) but below human-approved canonical pages.
    """
    now = dt.datetime.now(dt.UTC)
    count = 0
    for source_ref, title, text in pages:
        await upsert_document(
            session,
            source_type=source_type,
            source_ref=source_ref,
            title=title,
            text=text,
            acl_keys=acl_keys,
            freshness_at=now,
            authority=authority,
        )
        count += 1
    await session.commit()
    return count


async def upsert_document(
    session: AsyncSession,
    *,
    source_type: str,
    source_ref: str,
    title: str,
    text: str,
    acl_keys: list[str] | None = None,
    freshness_at: dt.datetime | None = None,
    authority: float = 0.5,
) -> None:
    """Upsert one chunk with EXPLICIT metadata — connectors pass the source's own
    modified time as freshness (ingestion time would fake staleness away). Does not
    commit; callers batch."""
    stmt = insert(KnowledgeChunk).values(
        source_type=source_type,
        source_ref=source_ref,
        title=title,
        text=text,
        acl_keys=acl_keys or ["public"],
        freshness_at=freshness_at,
        authority=authority,
    )
    stmt = stmt.on_conflict_do_update(
        # Matches the composite unique index; tenant_id is auto-set by the row default
        # (the current-tenant GUC), so the conflict target stays within the tenant.
        index_elements=["tenant_id", "source_type", "source_ref"],
        set_={
            "title": stmt.excluded.title,
            "text": stmt.excluded.text,
            "acl_keys": stmt.excluded.acl_keys,
            "freshness_at": stmt.excluded.freshness_at,
            "authority": stmt.excluded.authority,
            "embedding": None,
            "embedding_model": None,
            "embedding_dim": None,
        },
    )
    await session.execute(stmt)
