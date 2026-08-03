"""Effort eval (S6-7): leave-one-out over the ledger's completed rows.

For every completed, scope-stable entry: hide it, build a band from the OTHER entries'
analogs and deviation quantiles, score against its actual. Reports MAE/MdAE, interval
coverage vs the nominal q10–q90 (80%), and the mandatory naive-baseline delta
(PRINCIPLES #7: naive = raw analog median, uncalibrated).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from estimo_knowledge import LedgerEntryRow, find_analogs
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.asyncio.session import AsyncSession

from estimo_estimate.bands import band_from_analogs
from estimo_estimate.calibration import transfer_distribution


@dataclass
class EffortEvalResult:
    cases: int = 0
    absolute_errors: list[float] = field(default_factory=list)
    naive_absolute_errors: list[float] = field(default_factory=list)
    covered: int = 0
    skipped_no_analogs: int = 0

    @property
    def mae(self) -> float:
        return statistics.mean(self.absolute_errors) if self.absolute_errors else 0.0

    @property
    def mdae(self) -> float:
        return statistics.median(self.absolute_errors) if self.absolute_errors else 0.0

    @property
    def naive_mae(self) -> float:
        return statistics.mean(self.naive_absolute_errors) if self.naive_absolute_errors else 0.0

    @property
    def coverage(self) -> float:
        return self.covered / self.cases if self.cases else 0.0


async def leave_one_out(session: AsyncSession) -> EffortEvalResult:
    result = EffortEvalResult()
    rows = (
        (
            await session.execute(
                select(LedgerEntryRow).where(
                    LedgerEntryRow.actual_effort.is_not(None),
                    LedgerEntryRow.scope_changed.is_(False),
                )
            )
        )
        .scalars()
        .all()
    )
    distribution = await transfer_distribution(session)

    for row in rows:
        actual = float(row.actual_effort)  # type: ignore[arg-type]
        query = f"{row.item_title} {row.item_description or ''}"
        analogs = [
            card for card in await find_analogs(session, query, limit=6) if card.entry_id != row.id
        ]
        band = band_from_analogs(analogs, distribution)
        if band is None:
            result.skipped_no_analogs += 1
            continue
        result.cases += 1
        result.absolute_errors.append(abs(band.range.likely - actual))
        naive_values = [
            v
            for card in analogs
            if (
                v := (
                    card.actual_effort
                    if card.actual_effort is not None
                    else (card.estimate.likely if card.estimate else card.estimate_single)
                )
            )
            is not None
        ]
        naive = statistics.median(naive_values)
        result.naive_absolute_errors.append(abs(naive - actual))
        if band.range.optimistic <= actual <= band.range.pessimistic:
            result.covered += 1
    return result


def render_report(result: EffortEvalResult, *, today: str) -> str:
    delta = result.naive_mae - result.mae
    return "\n".join(
        [
            f"# S6 effort eval (leave-one-out) — {today}",
            "",
            "Seed-ledger leave-one-out: band from the remaining entries' analogs +",
            "deviation quantiles, scored against the held-out actual.",
            "",
            f"- Cases: {result.cases} (skipped, no analogs: {result.skipped_no_analogs})",
            f"- MAE: **{result.mae:.2f} pd** · MdAE: {result.mdae:.2f} pd",
            (
                f"- Naive baseline MAE (uncalibrated analog median): {result.naive_mae:.2f} pd "
                f"— delta **{delta:+.2f} pd**"
            ),
            f"- Interval coverage (nominal 80%, q10–q90): **{result.coverage:.0%}**",
            "",
            "Small-N caveat: quantiles are fit in-sample on ~15 seed rows (split-conformal",
            "arrives with a real ledger); these numbers prove the mechanism, not field",
            "accuracy.",
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="estimo-effort-eval")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    database_url = os.environ.get("ESTIMO_DATABASE_URL")
    if not database_url:
        raise SystemExit("ESTIMO_DATABASE_URL is not set")

    async def _run() -> EffortEvalResult:
        engine = create_async_engine(database_url)
        try:
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as session:
                return await leave_one_out(session)
        finally:
            await engine.dispose()

    result = asyncio.run(_run())
    report = render_report(result, today=args.date)
    args.report.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
