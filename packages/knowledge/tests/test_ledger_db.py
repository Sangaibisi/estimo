"""Ledger import + Turkish retrieval + analogy cards against real PostgreSQL."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

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


async def test_dense_similarity_is_measured_not_ranked(seeded: AsyncSession) -> None:
    """S12-6: the number behind a "81% match" chip.

    It has to be the cosine similarity between two vectors. An identical vector scores
    ~1.0 and an orthogonal one ~0.0 — a rank-derived score would have no way to tell
    those two apart, since both are simply "first" and "second".
    """
    from estimo_knowledge.search import dense_ledger_matches

    rows = list((await seeded.execute(select(LedgerEntryRow).limit(2))).scalars())
    same, orthogonal = rows[0], rows[1]
    for row, vector in ((same, [1.0, 0.0, 0.0, 0.0]), (orthogonal, [0.0, 1.0, 0.0, 0.0])):
        await seeded.execute(
            update(LedgerEntryRow)
            .where(LedgerEntryRow.id == row.id)
            .values(embedding=vector, embedding_model="mock", embedding_dim=4)
        )
    await seeded.commit()

    matches = dict(await dense_ledger_matches(seeded, [1.0, 0.0, 0.0, 0.0], limit=5))
    assert matches[same.id] == pytest.approx(1.0, abs=1e-6)
    assert matches[orthogonal.id] == pytest.approx(0.0, abs=1e-6)


async def test_a_slice_is_applied_inside_the_dense_leg(seeded: AsyncSession) -> None:
    """The slice must reach the SQL of BOTH legs, not just the lexical one."""
    from estimo_knowledge.search import dense_ledger_matches, ledger_slice_conditions

    rows = list((await seeded.execute(select(LedgerEntryRow).limit(2))).scalars())
    for row in rows:
        await seeded.execute(
            update(LedgerEntryRow)
            .where(LedgerEntryRow.id == row.id)
            .values(embedding=[1.0, 0.0, 0.0, 0.0], embedding_model="mock", embedding_dim=4)
        )
    await seeded.execute(
        update(LedgerEntryRow).where(LedgerEntryRow.id == rows[0].id).values(team="billing")
    )
    await seeded.execute(
        update(LedgerEntryRow).where(LedgerEntryRow.id == rows[1].id).values(team="charging")
    )
    await seeded.commit()

    matched = await dense_ledger_matches(
        seeded, [1.0, 0.0, 0.0, 0.0], limit=5, conditions=ledger_slice_conditions("billing", None)
    )
    assert [entry_id for entry_id, _ in matched] == [rows[0].id]


async def test_an_unmeasurable_distance_never_becomes_a_perfect_match(
    seeded: AsyncSession,
) -> None:
    """The clamp used to fail OPEN on the one non-finite input pgvector produces.

    A zero-vector embedding makes cosine distance undefined; pgvector returns NaN, and
    `min(1.0, nan)` is 1.0 because `nan < 1.0` is False — so the least comparable row
    in the ledger wore a "100% match" chip on the one screen whose whole claim is that
    its numbers are measured."""
    from estimo_knowledge.search import dense_ledger_matches

    rows = list((await seeded.execute(select(LedgerEntryRow).limit(2))).scalars())
    real, degenerate = rows[0], rows[1]
    for row, vector in ((real, [0.6, 0.8, 0.0, 0.0]), (degenerate, [0.0, 0.0, 0.0, 0.0])):
        await seeded.execute(
            update(LedgerEntryRow)
            .where(LedgerEntryRow.id == row.id)
            .values(embedding=vector, embedding_model="mock", embedding_dim=4)
        )
    await seeded.commit()

    matched = dict(await dense_ledger_matches(seeded, [1.0, 0.0, 0.0, 0.0], limit=5))
    assert matched[real.id] == pytest.approx(0.6, abs=1e-6)
    assert degenerate.id not in matched, "an undefined distance was served as a similarity"


async def test_a_measured_similarity_stays_on_its_own_row(seeded: AsyncSession) -> None:
    """Feedback reordering reshuffles the analog list AFTER retrieval scored it.

    Attaching scores positionally instead of by id would print one entry's measured
    percentage on another entry's card — the precise failure the percentage exists to
    rule out."""
    from estimo_knowledge.db import AnalogFeedback
    from estimo_knowledge.search import hybrid_ledger_matches

    # A query that matches EXACTLY these two rows, so the ±2-position feedback nudge
    # is guaranteed to reorder them rather than move one row inside a longer list.
    rows = list((await seeded.execute(select(LedgerEntryRow).limit(2))).scalars())
    for row, title, vector in (
        (rows[0], "zümrütlü fatura alfa", [1.0, 0.0, 0.0, 0.0]),
        (rows[1], "zümrütlü fatura beta", [0.6, 0.8, 0.0, 0.0]),
    ):
        await seeded.execute(
            update(LedgerEntryRow)
            .where(LedgerEntryRow.id == row.id)
            .values(item_title=title, embedding=vector, embedding_model="mock", embedding_dim=4)
        )
    await seeded.commit()

    class _StubClient:
        async def embed(self, texts: list[str]) -> Any:
            return SimpleNamespace(vectors=[[1.0, 0.0, 0.0, 0.0]])

    stub = _StubClient()
    retrieved = await hybrid_ledger_matches(seeded, "zümrütlü", client=stub, limit=5)  # type: ignore[arg-type]
    assert len(retrieved) == 2, "the query must isolate the two seeded rows"
    similarity = dict(retrieved)

    # Promote whichever row retrieval ranked LAST (PRINCIPLES #8 outcome feedback).
    seeded.add(
        AnalogFeedback(
            entry_id=retrieved[-1][0],
            origin_ref="estimate://test/WI-1",
            weight=2.0,
            reason="within-range",
        )
    )
    await seeded.commit()

    cards = await find_analogs(seeded, "zümrütlü", client=stub, limit=5)  # type: ignore[arg-type]
    # The card order is NOT the order retrieval scored. Without this the assertions
    # below would hold under positional attachment too, and prove nothing.
    assert [entry_id for entry_id, _ in retrieved] != [card.entry_id for card in cards]
    for card in cards:
        assert card.similarity == pytest.approx(similarity[card.entry_id], abs=1e-6)
    assert sorted(card.similarity or 0.0 for card in cards) == [
        pytest.approx(0.6, abs=1e-6),
        pytest.approx(1.0, abs=1e-6),
    ], "both measured values must survive, not one duplicated onto both rows"
