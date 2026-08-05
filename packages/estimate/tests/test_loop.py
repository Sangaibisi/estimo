"""S8 calibration loop: ledger upsert, analog feedback, snapshots, rolling coverage."""

import datetime as dt
import uuid
from pathlib import Path

import pytest
from estimo_estimate import record_actual, rolling_coverage
from estimo_estimate.loop import _feedback_weight, origin_ref
from estimo_knowledge import AnalogFeedback, CalibrationSnapshot, LedgerEntryRow, import_seed
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from estimo_core import EstimateLine, EvidenceRef, ThreePoint, WorkItem

pytestmark = pytest.mark.db

REPO_ROOT = Path(__file__).resolve().parents[3]
SEED = REPO_ROOT / "fixtures" / "seed" / "sample-seed.csv"


def _item(item_id: str = "WI-REQ-T-01") -> WorkItem:
    return WorkItem(
        id=item_id,
        brd_ref="AUR-BRD-2026-077",
        title="Taksitli fatura kırılımı geliştirmesi",
        description="Konsolide faturada taksit kırılımı",
        requirement_ids=("REQ-T-01",),
        module_tags=("billing-core",),
    )


def _line(item_id: str, analog_ids: list[uuid.UUID]) -> EstimateLine:
    return EstimateLine(
        work_item_id=item_id,
        range=ThreePoint(optimistic=4, likely=8, pessimistic=12),
        confidence="medium",
        evidence=tuple(
            EvidenceRef.from_uri(f"ledger://{analog_id}", label="analog")
            for analog_id in analog_ids
        ),
    )


class TestLoop:
    @pytest.fixture
    async def seeded(self, session: AsyncSession, clean_tables: None) -> AsyncSession:
        await session.execute(text("TRUNCATE calibration_snapshots"))
        report = await import_seed(session, SEED)
        assert report.rejected == []
        return session

    async def _analog_ids(self, session: AsyncSession, count: int = 2) -> list[uuid.UUID]:
        rows = await session.execute(select(LedgerEntryRow.id).limit(count))
        return [row for (row,) in rows]

    async def test_record_actual_upserts_feedback_and_snapshot(self, seeded: AsyncSession) -> None:
        estimate_id = uuid.uuid4()
        analog_ids = await self._analog_ids(seeded)
        item = _item()
        line = _line(item.id, analog_ids)

        row = await record_actual(
            seeded,
            estimate_id=estimate_id,
            brd_ref="AUR-BRD-2026-077",
            brd_title="Taksit",
            item=item,
            line=line,
            actual_effort=9,
            actual_source="timesheet",
        )
        assert row.origin_ref == origin_ref(estimate_id, item.id)
        assert row.actual_effort is not None and float(row.actual_effort) == 9

        feedback = list(
            (
                await seeded.execute(select(AnalogFeedback).order_by(AnalogFeedback.entry_id))
            ).scalars()
        )
        assert {f.entry_id for f in feedback} == set(analog_ids)
        assert all(float(f.weight) == 0.5 for f in feedback)  # 9 in [4, 12] => covered
        assert all(f.reason == "band-covered-actual" for f in feedback)

        snapshots = list((await seeded.execute(select(CalibrationSnapshot))).scalars())
        assert len(snapshots) == 1
        assert snapshots[0].trigger == "actual-recorded"
        coverage = snapshots[0].rolling_coverage
        assert coverage is not None and float(coverage) == 1.0  # the one product row covered

        # Re-recording REVISES: same ledger row, same feedback rows, new values.
        await record_actual(
            seeded,
            estimate_id=estimate_id,
            brd_ref="AUR-BRD-2026-077",
            brd_title="Taksit",
            item=item,
            line=line,
            actual_effort=30,
            actual_source="project-report",
        )
        rows = list(
            (
                await seeded.execute(
                    select(LedgerEntryRow).where(LedgerEntryRow.origin_ref.is_not(None))
                )
            ).scalars()
        )
        assert len(rows) == 1
        assert rows[0].actual_effort is not None and float(rows[0].actual_effort) == 30
        # The feedback upsert runs at the SQL layer; expire the identity map so the
        # re-select reads the revised weights instead of cached instances.
        seeded.expire_all()
        feedback = list((await seeded.execute(select(AnalogFeedback))).scalars())
        assert len(feedback) == len(analog_ids)
        assert all(float(f.weight) == -1.0 for f in feedback)  # ln(30/8) clamps to -1
        assert all(f.reason == "band-missed-actual" for f in feedback)

    async def test_scope_changed_stores_but_skips_feedback(self, seeded: AsyncSession) -> None:
        estimate_id = uuid.uuid4()
        analog_ids = await self._analog_ids(seeded)
        item = _item("WI-REQ-T-02")
        await record_actual(
            seeded,
            estimate_id=estimate_id,
            brd_ref="AUR-BRD-2026-078",
            brd_title="Kapsam değişti",
            item=item,
            line=_line(item.id, analog_ids),
            actual_effort=40,
            actual_source="timesheet",
            scope_changed=True,
        )
        stored = await seeded.scalar(
            select(LedgerEntryRow).where(
                LedgerEntryRow.origin_ref == origin_ref(estimate_id, item.id)
            )
        )
        assert stored is not None and stored.scope_changed is True
        assert list((await seeded.execute(select(AnalogFeedback))).scalars()) == []
        # The snapshot still fires — the series must register exclusions too —
        # but the excluded row contributes nothing to the coverage window.
        snapshots = list((await seeded.execute(select(CalibrationSnapshot))).scalars())
        assert len(snapshots) == 1
        assert await rolling_coverage(seeded) is None

    async def test_scope_changed_revision_withdraws_feedback(self, seeded: AsyncSession) -> None:
        """The designed honesty path: an actual first recorded normally, then
        corrected to scope_changed, must stop influencing analog ranking."""
        estimate_id = uuid.uuid4()
        analog_ids = await self._analog_ids(seeded)
        item = _item("WI-REQ-T-03")
        line = _line(item.id, analog_ids)
        await record_actual(
            seeded,
            estimate_id=estimate_id,
            brd_ref="AUR-BRD-2026-079",
            brd_title="Önce normal",
            item=item,
            line=line,
            actual_effort=9,
            actual_source="timesheet",
        )
        assert len(list((await seeded.execute(select(AnalogFeedback))).scalars())) == len(
            analog_ids
        )

        await record_actual(
            seeded,
            estimate_id=estimate_id,
            brd_ref="AUR-BRD-2026-079",
            brd_title="Önce normal",
            item=item,
            line=line,
            actual_effort=40,
            actual_source="timesheet",
            scope_changed=True,
        )
        seeded.expire_all()
        assert list((await seeded.execute(select(AnalogFeedback))).scalars()) == []

    async def test_discipline_is_normalized_and_stored(self, seeded: AsyncSession) -> None:
        """S13-3: the actuals form may say "FE"; the ledger stores the slice key."""
        estimate_id = uuid.uuid4()
        analog_ids = await self._analog_ids(seeded)
        item = _item("WI-REQ-T-09")
        row = await record_actual(
            seeded,
            estimate_id=estimate_id,
            brd_ref="AUR-BRD-2026-090",
            brd_title="Disiplinli",
            item=item,
            line=_line(item.id, analog_ids),
            actual_effort=5,
            actual_source="timesheet",
            discipline="FE",
        )
        assert row.discipline == "frontend"
        # And an unrecognized value refuses loudly instead of minting a slice.
        import pytest as _pytest

        with _pytest.raises(ValueError, match="discipline"):
            await record_actual(
                seeded,
                estimate_id=estimate_id,
                brd_ref="AUR-BRD-2026-090",
                brd_title="Disiplinli",
                item=item,
                line=_line(item.id, analog_ids),
                actual_effort=5,
                actual_source="timesheet",
                discipline="fullstack",
            )

    async def test_rebuilt_line_with_new_analogs_drops_stale_feedback(
        self, seeded: AsyncSession
    ) -> None:
        estimate_id = uuid.uuid4()
        analog_ids = await self._analog_ids(seeded, count=4)
        item = _item("WI-REQ-T-04")
        await record_actual(
            seeded,
            estimate_id=estimate_id,
            brd_ref="AUR-BRD-2026-080",
            brd_title="Rebuild",
            item=item,
            line=_line(item.id, analog_ids[:2]),
            actual_effort=9,
            actual_source="timesheet",
        )
        # Re-record against a rebuilt line citing DIFFERENT analogs: the old
        # analogs' weights must not outlive their evidence.
        await record_actual(
            seeded,
            estimate_id=estimate_id,
            brd_ref="AUR-BRD-2026-080",
            brd_title="Rebuild",
            item=item,
            line=_line(item.id, analog_ids[2:]),
            actual_effort=9,
            actual_source="timesheet",
        )
        seeded.expire_all()
        feedback = list((await seeded.execute(select(AnalogFeedback))).scalars())
        assert {f.entry_id for f in feedback} == set(analog_ids[2:])

    async def test_rolling_coverage_ignores_rows_the_product_did_not_estimate(
        self, seeded: AsyncSession
    ) -> None:
        """`origin_ref IS NOT NULL` also matches the Jira connector's `jira://` rows.

        Those are somebody else's numbers. Counting them here grades the pipeline on
        estimates it never made — and the drift signal is exactly the number nobody
        should be able to move without having made an estimate.
        """
        from estimo_knowledge import LedgerEntryRow

        seeded.add(
            LedgerEntryRow(
                brd_ref="ACME-42",
                item_title="Connector row",
                origin_ref="jira://ACME-42",
                est_optimistic=1,
                est_likely=2,
                est_pessimistic=3,
                actual_effort=40.0,
                actual_source="project-report",
            )
        )
        seeded.add(
            LedgerEntryRow(
                brd_ref="BRD-1",
                item_title="Product row",
                origin_ref=f"estimate://{uuid.uuid4()}/WI-1",
                est_optimistic=8,
                est_likely=10,
                est_pessimistic=17,
                actual_effort=12.0,
                actual_source="timesheet",
            )
        )
        await seeded.commit()

        rolling = await rolling_coverage(seeded)
        assert rolling is not None
        assert rolling.samples == 1, "a connector row entered the rolling window"
        assert rolling.coverage == 1.0

    async def test_the_rolling_window_is_the_last_JOBS_not_the_last_rows_written(
        self, seeded: AsyncSession
    ) -> None:
        """A seed import commits every row in one transaction.

        `created_at` then ties across the whole file, so "the last 20" degenerates into
        an arbitrary 20 — on a 212-row imported ledger the drift signal would be
        computed from a subset nobody chose. The window orders by when the work
        finished. The ids below are pinned so the wrong ordering has a KNOWN wrong
        answer rather than a random one.
        """
        from estimo_knowledge import LedgerEntryRow

        stale_miss = uuid.UUID("00000000-0000-0000-0000-000000000001")
        for index in range(6):
            seeded.add(
                LedgerEntryRow(
                    id=uuid.UUID(f"ffffffff-0000-0000-0000-{index:012d}"),
                    brd_ref=f"BRD-{index}",
                    item_title="Recent job",
                    origin_ref=f"estimate://{uuid.uuid4()}/WI-{index}",
                    est_optimistic=8,
                    est_likely=10,
                    est_pessimistic=17,
                    actual_effort=12.0,
                    actual_source="timesheet",
                    completed_at=dt.date(2026, 6, 1) + dt.timedelta(days=index),
                )
            )
        seeded.add(
            LedgerEntryRow(
                # Smallest id, so an ordering that falls back to it puts this row FIRST.
                id=stale_miss,
                brd_ref="BRD-OLD",
                item_title="Job finished years ago",
                origin_ref=f"estimate://{uuid.uuid4()}/WI-OLD",
                est_optimistic=8,
                est_likely=10,
                est_pessimistic=17,
                actual_effort=99.0,
                actual_source="timesheet",
                completed_at=dt.date(2019, 1, 1),
            )
        )
        await seeded.commit()

        rolling = await rolling_coverage(seeded, window=6)
        assert rolling is not None
        assert rolling.samples == 6
        assert rolling.coverage == 1.0, "the window included a job that finished years ago"

    async def test_a_job_that_never_said_when_it_finished_still_enters_the_window(
        self, seeded: AsyncSession
    ) -> None:
        """`completed_at` is optional on the product's own write path.

        The web client does not send it at all, so ordering dated rows ahead of undated
        ones parks the window on whatever imported history happens to carry dates — and
        the product's own recent work can never enter the drift signal. An undated row
        is dated by when it was recorded, which is the best fact there is.
        """
        from estimo_knowledge import LedgerEntryRow

        for index in range(6):
            seeded.add(
                LedgerEntryRow(
                    brd_ref=f"OLD-{index}",
                    item_title="Old job that missed its band",
                    origin_ref=f"estimate://{uuid.uuid4()}/WI-OLD-{index}",
                    est_optimistic=8,
                    est_likely=10,
                    est_pessimistic=17,
                    actual_effort=99.0,
                    actual_source="timesheet",
                    completed_at=dt.date(2019, 1, 1),
                )
            )
        await seeded.commit()
        for index in range(6):
            seeded.add(
                LedgerEntryRow(
                    brd_ref=f"NEW-{index}",
                    item_title="Recent job recorded through the product",
                    origin_ref=f"estimate://{uuid.uuid4()}/WI-NEW-{index}",
                    est_optimistic=8,
                    est_likely=10,
                    est_pessimistic=17,
                    actual_effort=12.0,
                    actual_source="timesheet",
                    completed_at=None,
                )
            )
        await seeded.commit()

        rolling = await rolling_coverage(seeded, window=6)
        assert rolling is not None
        assert rolling.samples == 6
        assert rolling.coverage == 1.0, "undated recent jobs were evicted by dated old ones"


def test_feedback_weight_shape() -> None:
    line = _line("WI-X", [uuid.uuid4()])
    covered, covered_reason = _feedback_weight(8, line)
    assert covered == 0.5 and covered_reason == "band-covered-actual"
    edge, _ = _feedback_weight(12, line)
    assert edge == 0.5  # band edges count as covered
    missed, missed_reason = _feedback_weight(13, line)
    assert missed_reason == "band-missed-actual"
    assert -1.0 <= missed < 0  # proportional to log error, capped
    huge_miss, _ = _feedback_weight(1000, line)
    assert huge_miss == -1.0
