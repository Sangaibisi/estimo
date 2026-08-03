"""S8-2: outcome feedback folds into analog ranking as a bounded, deterministic nudge."""

import uuid
from pathlib import Path

import pytest
from estimo_knowledge import AnalogFeedback, find_analogs, import_seed
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.db

REPO_ROOT = Path(__file__).resolve().parents[3]
SEED = REPO_ROOT / "fixtures" / "seed" / "sample-seed.csv"

QUERY = "taksitli fatura kampanya"


class TestFeedbackRanking:
    @pytest.fixture
    async def seeded(self, session: AsyncSession, clean_tables: None) -> AsyncSession:
        report = await import_seed(session, SEED)
        assert report.rejected == []
        return session

    async def test_negative_feedback_demotes_within_clamp(self, seeded: AsyncSession) -> None:
        baseline = await find_analogs(seeded, QUERY, limit=5)
        assert len(baseline) >= 3
        top = baseline[0]

        # A pile of bad outcomes for the top analog: cumulative -5, clamped to -2.
        for _ in range(5):
            seeded.add(
                AnalogFeedback(
                    entry_id=top.entry_id,
                    origin_ref=f"estimate://{uuid.uuid4()}/WI-X",
                    weight=-1.0,
                    reason="band-missed-actual",
                )
            )
        await seeded.flush()

        adjusted = await find_analogs(seeded, QUERY, limit=5)
        new_position = next(
            index for index, card in enumerate(adjusted) if card.entry_id == top.entry_id
        )
        assert 0 < new_position <= 2  # demoted, but never further than the clamp allows
        # Retrieval similarity stays primary: the set of analogs is unchanged.
        assert {card.entry_id for card in adjusted} == {card.entry_id for card in baseline}

    async def test_positive_feedback_promotes(self, seeded: AsyncSession) -> None:
        baseline = await find_analogs(seeded, QUERY, limit=5)
        last = baseline[-1]
        for index in range(3):
            seeded.add(
                AnalogFeedback(
                    entry_id=last.entry_id,
                    origin_ref=f"estimate://{uuid.uuid4()}/WI-{index}",
                    weight=1.0,
                    reason="band-covered-actual",
                )
            )
        await seeded.flush()
        adjusted = await find_analogs(seeded, QUERY, limit=5)
        new_position = next(
            index for index, card in enumerate(adjusted) if card.entry_id == last.entry_id
        )
        assert new_position < len(baseline) - 1  # moved up

    async def test_no_feedback_keeps_retrieval_order(self, seeded: AsyncSession) -> None:
        first = await find_analogs(seeded, QUERY, limit=5)
        second = await find_analogs(seeded, QUERY, limit=5)
        assert [card.entry_id for card in first] == [card.entry_id for card in second]
