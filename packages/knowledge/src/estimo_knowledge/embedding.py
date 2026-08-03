"""Indexer-side embedding writer (S11-8).

Until this existed, nothing in the repository ever wrote an embedding: the only
`.embed()` call embedded the *query*, and every stored row carried NULL vectors. So
`dense_ledger_ids` filtered `embedding IS NOT NULL` against zero rows and RRF fused a
single ranking — retrieval was lexical everywhere, while the architecture described it
as hybrid. The dense code was correct; it had no data.

Design notes worth keeping:

- **The gateway is the only model surface** (ADR-0001). No provider SDK, no model name
  — a *profile* (`embedding`) is resolved by the deployment.
- **Optional, and inert without a gateway.** A deployment with no embedding profile
  keeps behaving exactly as before rather than failing.
- **The model id and dimension are stored per row**, so swapping embedders never
  silently mixes vector spaces: `dense_ledger_ids` filters on the query's dimension,
  which means old-model rows fall out of the dense leg instead of scoring nonsense
  against it. Re-embedding is then a backfill, not a migration.
- **Batches commit independently.** A rate limit halfway through a 10k backfill must
  leave the first half persisted; the next run picks up exactly what is still NULL.
- **Text is capped before sending.** There is no chunker yet (S11-2), so a "chunk" is
  a whole Confluence page and can exceed any embedder's context. Silently sending it
  would fail the batch — and one oversized page must not stall the queue behind it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from estimo_gateway import GatewayClient, GatewayError
from estimo_knowledge.db import KnowledgeChunk, LedgerEntryRow

logger = logging.getLogger("estimo.knowledge.embedding")

# Roughly 8k tokens at ~4 chars/token, the smallest context among embedders anyone
# would plausibly deploy. Truncation is logged, never silent: a page long enough to be
# cut is a page whose tail is unsearchable, which the operator should know about.
MAX_EMBED_CHARS = 32_000

# Small enough that one failure loses little work, large enough to amortize round trips.
DEFAULT_BATCH_SIZE = 64


@dataclass(frozen=True)
class EmbedReport:
    """What a run actually did — reported rather than inferred from a log line."""

    embedded: int = 0
    truncated: int = 0
    failed_batches: int = 0
    model: str | None = None
    dimension: int | None = None

    @property
    def ok(self) -> bool:
        return self.failed_batches == 0


def embed_text(title: str | None, body: str | None) -> str:
    """The single canonical definition of what gets embedded for a row.

    Title first: it carries the space key and page name the Confluence lane prefixes
    on, which is often the only topical signal in a body full of tables.
    """
    return "\n".join(part for part in ((title or "").strip(), (body or "").strip()) if part)


def _capped(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_EMBED_CHARS:
        return text, False
    return text[:MAX_EMBED_CHARS], True


async def embed_pending(
    session: AsyncSession,
    client: GatewayClient | None,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    limit: int | None = None,
) -> EmbedReport:
    """Give every un-embedded chunk and ledger row a vector. Idempotent.

    Selects only rows whose `embedding IS NULL`, so re-running after a partial failure
    resumes rather than recomputing, and a steady state costs one query. Returns a
    report; the caller decides whether a partial run is acceptable.
    """
    if client is None:
        return EmbedReport()

    embedded = truncated = failed = 0
    model: str | None = None
    dimension: int | None = None

    for entity, title_col, body_col in (
        (KnowledgeChunk, KnowledgeChunk.title, KnowledgeChunk.text),
        (LedgerEntryRow, LedgerEntryRow.item_title, LedgerEntryRow.item_description),
    ):
        remaining = limit
        while remaining is None or remaining > 0:
            take = batch_size if remaining is None else min(batch_size, remaining)
            stmt = (
                select(entity.id, title_col, body_col)
                .where(entity.embedding.is_(None))
                .order_by(entity.id)
                .limit(take)
            )
            rows = (await session.execute(stmt)).all()
            if not rows:
                break

            texts: list[str] = []
            ids: list[Any] = []
            for row_id, title, body in rows:
                text, was_cut = _capped(embed_text(title, body))
                if was_cut:
                    truncated += 1
                    logger.warning(
                        "embed text truncated to %d chars: %s id=%s",
                        MAX_EMBED_CHARS,
                        entity.__tablename__,
                        row_id,
                    )
                if not text:
                    # Nothing to embed. Skipping would re-select this row forever, so
                    # a single space keeps the queue moving and the row joins the dense
                    # leg with a meaningless vector rather than blocking the backfill.
                    text = " "
                texts.append(text)
                ids.append(row_id)

            try:
                result = await client.embed(texts)
            except GatewayError:
                # One bad batch must not abandon the rest of the backfill.
                #
                # Deliberately NO rollback: the failure happened in an HTTP call, and
                # nothing has been written since the previous batch committed, so there
                # is nothing to undo. Rolling back here reached into a session this
                # function does not own and expired the caller's ORM objects — which
                # silently reverted `SyncRun.status` from "succeeded" back to its last
                # committed value, "running", leaving a finished crawl to occupy the
                # one-running-sync index until the hourly sweep freed it.
                failed += 1
                logger.warning(
                    "embedding batch failed (%s, %d rows); continuing",
                    entity.__tablename__,
                    len(ids),
                    exc_info=True,
                )
                break

            model, dimension = result.model, result.dimension
            for row_id, vector in zip(ids, result.vectors, strict=True):
                await session.execute(
                    update(entity)
                    .where(entity.id == row_id)
                    .values(
                        embedding=vector,
                        embedding_model=result.model,
                        embedding_dim=result.dimension,
                    )
                )
            # Commit per batch: a later rate limit must not undo this work.
            await session.commit()
            embedded += len(ids)
            if remaining is not None:
                remaining -= len(ids)
            if len(rows) < take:
                break

    return EmbedReport(
        embedded=embedded,
        truncated=truncated,
        failed_batches=failed,
        model=model,
        dimension=dimension,
    )
