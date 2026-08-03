"""Ledger import + Turkish retrieval + analogy cards against real PostgreSQL."""

import json
from pathlib import Path

import pytest
from estimo_knowledge import (
    KnowledgeChunk,
    LedgerEntryRow,
    find_analogs,
    import_seed,
    lexical_chunk_ids,
    lexical_ledger_ids,
)
from estimo_knowledge.search import dense_ledger_ids
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.db

REPO_ROOT = Path(__file__).resolve().parents[3]
SEED = REPO_ROOT / "fixtures" / "seed" / "sample-seed.csv"
BROKEN = REPO_ROOT / "fixtures" / "seed" / "broken-sample.csv"
GOLDEN = REPO_ROOT / "evals" / "golden" / "retrieval-tr" / "queries.json"

AURORA_MODULES = {
    "billing-core",
    "crm-suite",
    "product-catalog",
    "campaign-engine",
    "dealer-portal",
    "integration-hub",
    "payment-adapter",
    "invoice-render",
    "selfcare-web",
}


@pytest.fixture
async def seeded(session: AsyncSession, clean_tables: None) -> AsyncSession:
    report = await import_seed(session, SEED, taxonomy=AURORA_MODULES)
    assert report.rejected == []
    return session


async def test_sample_seed_imports_fully(seeded: AsyncSession) -> None:
    count = await seeded.scalar(select(func.count()).select_from(LedgerEntryRow))
    assert count == 18


async def test_unknown_module_goes_to_review_queue(
    session: AsyncSession, clean_tables: None
) -> None:
    report = await import_seed(session, SEED, taxonomy={"billing-core"})
    assert report.imported == 18
    assert "campaign-engine" in report.unknown_modules


async def test_broken_rows_rejected_with_reasons(session: AsyncSession, clean_tables: None) -> None:
    report = await import_seed(session, BROKEN)
    assert report.imported == 1  # only the valid control row
    assert len(report.rejected) == 4
    reasons = " | ".join(r["error"] for r in report.rejected)
    assert "item_title" in reasons
    assert "exactly one" in reasons  # missing estimate
    assert "actual_source" in reasons
    assert "scope_changed" in reasons


async def test_turkish_lexical_golden_queries(seeded: AsyncSession) -> None:
    """S3-5 retrieval eval: every golden query's expected titles in top-k."""
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    top_k = golden["top_k"]
    for case in golden["queries"]:
        ids = await lexical_ledger_ids(seeded, case["query"], limit=top_k)
        rows = (
            (await seeded.execute(select(LedgerEntryRow).where(LedgerEntryRow.id.in_(ids))))
            .scalars()
            .all()
        )
        titles = [row.item_title for row in rows]
        for expected in case["expect_titles"]:
            assert any(expected in title for title in titles), (
                f"query {case['query']!r}: {expected!r} not in top-{top_k} {titles}"
            )


async def test_analogy_cards_carry_outside_view(seeded: AsyncSession) -> None:
    cards = await find_analogs(seeded, "konsolide fatura üretimi", limit=5)
    assert cards, "no analogs found"
    top = cards[0]
    assert "Konsolide" in top.item_title
    assert top.estimate is not None
    assert top.deviation == pytest.approx(28 / 22, rel=1e-3)
    assert top.actual_source == "timesheet"


async def test_acl_prefilter_on_chunks(session: AsyncSession, clean_tables: None) -> None:
    session.add_all(
        [
            KnowledgeChunk(
                source_type="wiki",
                source_ref="wiki://100@1",
                title="Fatura süreci",
                text="Konsolide fatura üretim süreci genel bakış.",
                acl_keys=["public"],
            ),
            KnowledgeChunk(
                source_type="wiki",
                source_ref="wiki://200@1",
                title="Fatura altyapı sırları",
                text="Konsolide fatura altyapısının ekip içi detayları.",
                acl_keys=["team-billing"],
            ),
        ]
    )
    await session.commit()

    public_only = await lexical_chunk_ids(session, "konsolide fatura", acl_keys=["public"])
    assert len(public_only) == 1

    both = await lexical_chunk_ids(session, "konsolide fatura", acl_keys=["public", "team-billing"])
    assert len(both) == 2


async def test_dense_leg_respects_dimension(seeded: AsyncSession) -> None:
    target = await seeded.scalar(
        select(LedgerEntryRow).where(LedgerEntryRow.item_title.contains("Konsolide fatura üretimi"))
    )
    assert target is not None
    await seeded.execute(
        update(LedgerEntryRow)
        .where(LedgerEntryRow.id == target.id)
        .values(embedding=[1.0, 0.0, 0.0, 0.0], embedding_model="mock", embedding_dim=4)
    )
    await seeded.commit()

    near = await dense_ledger_ids(seeded, [0.9, 0.1, 0.0, 0.0], limit=3)
    assert near == [target.id]
    other_dim = await dense_ledger_ids(seeded, [0.9, 0.1], limit=3)
    assert other_dim == []


async def test_code_wiki_chunks_upsert_replaces(session: AsyncSession, clean_tables: None) -> None:
    from estimo_knowledge import lexical_chunk_ids, upsert_generated_chunks

    pages = [
        (
            "repo://meridyen-mini@fixture/billing-core",
            "Module: billing-core",
            "Taksit planı yaşam döngüsü ve fatura kalemi yazımı.",
        )
    ]
    assert await upsert_generated_chunks(session, pages) == 1
    assert await upsert_generated_chunks(session, pages) == 1  # re-ingest replaces
    hits = await lexical_chunk_ids(session, "taksit planı", acl_keys=["public"])
    assert len(hits) == 1
