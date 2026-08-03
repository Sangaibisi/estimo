"""S11-8: the indexer-side embedding writer, and the re-ingest trap it must survive."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from estimo_knowledge import upsert_document
from estimo_knowledge.db import KnowledgeChunk
from estimo_knowledge.embedding import MAX_EMBED_CHARS, embed_pending, embed_text
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimo_gateway import GatewayError

pytestmark = pytest.mark.db

DIM = 8


class FakeEmbedder:
    """Stands in for the gateway. Deterministic, and counts calls so the tests can
    assert on how much embedding work was actually requested."""

    def __init__(self, *, fail_after: int | None = None) -> None:
        self.calls: list[list[str]] = []
        self.fail_after = fail_after

    async def embed(self, texts: list[str], *, stage: str = "embedding") -> Any:
        self.calls.append(list(texts))
        if self.fail_after is not None and len(self.calls) > self.fail_after:
            raise GatewayError("simulated gateway failure")

        return SimpleNamespace(
            vectors=[[float(len(text) % 7) / 7.0] * DIM for text in texts],
            model="fake-embed-v1",
            dimension=DIM,
        )

    @property
    def embedded_texts(self) -> list[str]:
        return [text for call in self.calls for text in call]


async def _chunk(session: AsyncSession, ref: str, title: str, text: str) -> None:
    await upsert_document(session, source_type="confluence", source_ref=ref, title=title, text=text)
    await session.commit()


async def test_embed_pending_fills_vectors_and_is_idempotent(
    session: AsyncSession, clean_tables: None
) -> None:
    for index in range(3):
        await _chunk(session, f"wiki://p{index}@1", f"Sayfa {index}", f"Taksitlendirme {index}")

    client = FakeEmbedder()
    report = await embed_pending(session, client)  # type: ignore[arg-type]
    assert report.embedded == 3
    assert report.model == "fake-embed-v1" and report.dimension == DIM
    assert report.ok

    rows = (await session.execute(select(KnowledgeChunk))).scalars().all()
    assert all(row.embedding is not None for row in rows)
    assert all(row.embedding_dim == DIM for row in rows)

    # Re-running embeds nothing: the queue is rows whose embedding IS NULL.
    again = await embed_pending(session, client)  # type: ignore[arg-type]
    assert again.embedded == 0


async def test_reingesting_unchanged_text_does_not_wipe_the_vector(
    session: AsyncSession, clean_tables: None
) -> None:
    """The Confluence lane re-ingests an overlap window of UNCHANGED pages on every
    incremental sync. An unconditional embedding reset would wipe those vectors on
    each run and re-bill the embedder forever to recompute identical text."""
    await _chunk(session, "wiki://stable@1", "Sabit", "Taksitlendirme kuralları")
    client = FakeEmbedder()
    assert (await embed_pending(session, client)).embedded == 1  # type: ignore[arg-type]

    # Same title and text arriving again — only freshness/authority differ.
    await upsert_document(
        session,
        source_type="confluence",
        source_ref="wiki://stable@1",
        title="Sabit",
        text="Taksitlendirme kuralları",
        authority=0.9,
    )
    await session.commit()

    row = (await session.execute(select(KnowledgeChunk))).scalar_one()
    assert row.embedding is not None, "an unchanged re-ingest destroyed the vector"
    assert (await embed_pending(session, client)).embedded == 0  # type: ignore[arg-type]
    assert len(client.embedded_texts) == 1, "identical text was embedded twice"


async def test_changed_text_invalidates_and_re_embeds(
    session: AsyncSession, clean_tables: None
) -> None:
    """The mirror property: a stale vector for edited text is worse than no vector,
    because it retrieves confidently against content that no longer says that."""
    await _chunk(session, "wiki://edited@1", "Başlık", "İlk sürüm")
    client = FakeEmbedder()
    await embed_pending(session, client)  # type: ignore[arg-type]

    await upsert_document(
        session,
        source_type="confluence",
        source_ref="wiki://edited@1",
        title="Başlık",
        text="Tamamen farklı bir içerik",
    )
    await session.commit()

    row = (await session.execute(select(KnowledgeChunk))).scalar_one()
    assert row.embedding is None, "edited text kept a vector describing the old text"
    assert (await embed_pending(session, client)).embedded == 1  # type: ignore[arg-type]


async def test_a_failed_batch_keeps_earlier_batches_and_reports_it(
    session: AsyncSession, clean_tables: None
) -> None:
    """A rate limit halfway through a backfill must not undo the committed half, and
    must not report success."""
    for index in range(4):
        await _chunk(session, f"wiki://b{index}@1", f"B{index}", f"metin {index}")

    client = FakeEmbedder(fail_after=1)
    report = await embed_pending(session, client, batch_size=2)  # type: ignore[arg-type]
    assert report.embedded == 2, "the batch that succeeded must stay persisted"
    assert report.failed_batches == 1
    assert not report.ok, "a partial run must not look like a success"

    done = (
        (await session.execute(select(KnowledgeChunk).where(KnowledgeChunk.embedding.is_not(None))))
        .scalars()
        .all()
    )
    assert len(done) == 2


async def test_oversized_text_is_capped_and_reported(
    session: AsyncSession, clean_tables: None
) -> None:
    """There is no chunker yet, so a 'chunk' is a whole page and can exceed any
    embedder's context. One oversized page must not fail the batch behind it."""
    await _chunk(session, "wiki://big@1", "Büyük", "a" * (MAX_EMBED_CHARS + 5_000))
    client = FakeEmbedder()
    report = await embed_pending(session, client)  # type: ignore[arg-type]

    assert report.embedded == 1
    assert report.truncated == 1
    assert len(client.embedded_texts[0]) == MAX_EMBED_CHARS


async def test_no_gateway_is_inert(session: AsyncSession, clean_tables: None) -> None:
    await _chunk(session, "wiki://none@1", "Yok", "metin")
    report = await embed_pending(session, None)
    assert report.embedded == 0 and report.ok
    row = (await session.execute(select(KnowledgeChunk))).scalar_one()
    assert row.embedding is None


def test_embed_text_puts_the_title_first() -> None:
    assert embed_text("[AUR] Fatura", "gövde") == "[AUR] Fatura\ngövde"
    assert embed_text(None, "gövde") == "gövde"
    assert embed_text("  ", "  ") == ""


async def test_the_dense_leg_finally_returns_rows(
    session: AsyncSession, clean_tables: None
) -> None:
    """The point of the whole exercise. `dense_ledger_ids` filters on
    `embedding IS NOT NULL`; with no writer it matched zero rows for the entire life
    of the project, so RRF fused a single ranking and 'hybrid' retrieval was lexical.
    """
    from estimo_knowledge.db import LedgerEntryRow
    from estimo_knowledge.search import dense_ledger_ids

    for index in range(3):
        session.add(
            LedgerEntryRow(
                brd_ref=f"AUR-{index}",
                item_title=f"Taksitlendirme kalemi {index}",
                item_description="Fatura bazlı taksitlendirme akışı",
            )
        )
    await session.commit()

    probe = [0.5] * DIM
    assert await dense_ledger_ids(session, probe) == [], "no vectors, no dense results"

    report = await embed_pending(session, FakeEmbedder())  # type: ignore[arg-type]
    assert report.embedded == 3

    hits = await dense_ledger_ids(session, probe)
    assert len(hits) == 3, "the dense leg still matches nothing after embedding"


async def test_a_different_embedder_dimension_is_excluded_not_mixed(
    session: AsyncSession, clean_tables: None
) -> None:
    """Swapping embedders must drop old rows OUT of the dense leg, never score them
    in the wrong vector space — which is why the dimension is stored per row."""
    from estimo_knowledge.db import LedgerEntryRow
    from estimo_knowledge.search import dense_ledger_ids

    session.add(LedgerEntryRow(brd_ref="AUR-9", item_title="Kalem", item_description="metin"))
    await session.commit()
    await embed_pending(session, FakeEmbedder())  # type: ignore[arg-type]

    assert len(await dense_ledger_ids(session, [0.5] * DIM)) == 1
    # A query embedded by a DIFFERENT model, with a different width.
    assert await dense_ledger_ids(session, [0.5] * (DIM + 4)) == []
