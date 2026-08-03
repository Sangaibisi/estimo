"""Chunk ingestion glue: generated pages (e.g. S5 module wikis) → knowledge_chunks.

A database-backed upsert on the (source_type, source_ref) unique index — regenerated
pages replace their previous version atomically, so concurrent re-ingestion cannot
duplicate. Embedding columns are explicitly reset: new text invalidates old vectors.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

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
    count = 0
    now = dt.datetime.now(dt.UTC)
    for source_ref, title, text in pages:
        stmt = insert(KnowledgeChunk).values(
            source_type=source_type,
            source_ref=source_ref,
            title=title,
            text=text,
            acl_keys=acl_keys or ["public"],
            freshness_at=now,
            authority=authority,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["source_type", "source_ref"],
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
        count += 1
    await session.commit()
    return count
