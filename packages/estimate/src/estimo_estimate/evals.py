"""Effort eval (S6-7 + S13-6): leave-one-out over the ledger's completed rows.

For every completed, scope-stable entry: hide it, build a band from the OTHER entries'
analogs and deviation quantiles, score against its actual. Reports MAE/MdAE, interval
coverage vs the nominal q10–q90 (80%), and the mandatory naive-baseline delta
(PRINCIPLES #7: naive = raw analog median, uncalibrated).

S13-6 adds the FRONTIER arm: a free-form LLM band per held-out row — item text only,
no analogs, no band constraint — measured on the same MAE/coverage axes. The arm is
opt-in (`--frontier` + a configured gateway): the offline harness stays deterministic,
CI stays network-free, and it is these measured numbers — not model citations — that
decide any future number-policy change.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from estimo_knowledge import LedgerEntryRow, find_analogs
from estimo_parse import DATA_SYSTEM, fence, redact_anchors
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.asyncio.session import AsyncSession

from estimo_estimate.bands import band_from_analogs
from estimo_estimate.calibration import transfer_distribution
from estimo_estimate.prompts import load_package_prompt
from estimo_gateway import GatewayClient, GatewayError, deployment_gateway_client

logger = logging.getLogger("estimo.estimate.evals")


@dataclass
class EffortEvalResult:
    cases: int = 0
    absolute_errors: list[float] = field(default_factory=list)
    naive_absolute_errors: list[float] = field(default_factory=list)
    covered: int = 0
    skipped_no_analogs: int = 0
    # Frontier arm (S13-6). Its own case count: the arm answers on rows the
    # calibrated arm skips for lack of analogs (that is much of its point), and a
    # row it fails on drops out of ITS average only.
    frontier_cases: int = 0
    frontier_absolute_errors: list[float] = field(default_factory=list)
    frontier_covered: int = 0
    frontier_failed: int = 0
    prompt_ids: list[str] = field(default_factory=list)

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

    @property
    def frontier_mae(self) -> float:
        return (
            statistics.mean(self.frontier_absolute_errors) if self.frontier_absolute_errors else 0.0
        )

    @property
    def frontier_coverage(self) -> float:
        return self.frontier_covered / self.frontier_cases if self.frontier_cases else 0.0

    def as_dict(self) -> dict[str, object]:
        """The machine-readable half of the report (evals/README.md: MD + JSON)."""
        return {
            "cases": self.cases,
            "skipped_no_analogs": self.skipped_no_analogs,
            "mae": round(self.mae, 3),
            "mdae": round(self.mdae, 3),
            "naive_mae": round(self.naive_mae, 3),
            "coverage": round(self.coverage, 3),
            "frontier": {
                "cases": self.frontier_cases,
                "mae": round(self.frontier_mae, 3),
                "coverage": round(self.frontier_coverage, 3),
                "failed": self.frontier_failed,
            }
            if self.frontier_cases or self.frontier_failed
            else None,
            "prompt_ids": self.prompt_ids,
        }


async def _frontier_band(
    client: GatewayClient, item_text: str
) -> tuple[float, float, float] | None:
    """One free-form band. The item text is REDACTED first — this arm sees the
    widest payload in the harness and the planted-anchor rule (PRINCIPLES #5)
    applies to eval traffic exactly as it does to product traffic."""
    prompt = load_package_prompt("frontier")
    try:
        result = await client.complete(
            "frontier",
            [
                {"role": "system", "content": DATA_SYSTEM},
                {
                    "role": "user",
                    "content": f"{prompt.text}\n\nWork item:\n{fence(redact_anchors(item_text))}",
                },
            ],
            temperature=0.0,
            max_tokens=200,
        )
        payload = json.loads(result.text)
        optimistic = float(payload["optimistic"])
        likely = float(payload["likely"])
        pessimistic = float(payload["pessimistic"])
        if not (0 < optimistic <= likely <= pessimistic):
            raise ValueError("band not ordered/positive")
    except (GatewayError, json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
        logger.warning("frontier arm failed on one row: %s", exc)
        return None
    return optimistic, likely, pessimistic


async def leave_one_out(
    session: AsyncSession, *, client: GatewayClient | None = None, frontier: bool = False
) -> EffortEvalResult:
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
    run_frontier = frontier and client is not None
    if run_frontier:
        result.prompt_ids.append(load_package_prompt("frontier").id)

    for row in rows:
        actual = float(row.actual_effort)  # type: ignore[arg-type]
        query = f"{row.item_title} {row.item_description or ''}"

        if run_frontier and client is not None:
            band_values = await _frontier_band(client, query)
            if band_values is None:
                result.frontier_failed += 1
            else:
                optimistic, likely, pessimistic = band_values
                result.frontier_cases += 1
                result.frontier_absolute_errors.append(abs(likely - actual))
                if optimistic <= actual <= pessimistic:
                    result.frontier_covered += 1

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
    lines = [
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
    ]
    if result.frontier_cases or result.frontier_failed:
        lines += [
            (
                f"- Frontier arm (free-form LLM, no analogs): MAE **{result.frontier_mae:.2f} pd** "
                f"· coverage **{result.frontier_coverage:.0%}** "
                f"(n={result.frontier_cases}, failed={result.frontier_failed})"
            ),
        ]
    if result.prompt_ids:
        lines.append(f"- Prompts: {', '.join(result.prompt_ids)}")
    lines += [
        "",
        "Small-N caveat: quantiles are fit in-sample on ~15 seed rows (split-conformal",
        "arrives with a real ledger); these numbers prove the mechanism, not field",
        "accuracy.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(prog="estimo-effort-eval")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument(
        "--frontier",
        action="store_true",
        help="also run the free-form LLM arm (needs a configured gateway)",
    )
    args = parser.parse_args()
    database_url = os.environ.get("ESTIMO_DATABASE_URL")
    if not database_url:
        raise SystemExit("ESTIMO_DATABASE_URL is not set")

    async def _run() -> EffortEvalResult:
        engine = create_async_engine(database_url)
        client: GatewayClient | None = None
        try:
            if args.frontier:
                # Panel override first, env as bootstrap — same rule as every CLI.
                client = await deployment_gateway_client(engine)
                if client is None:
                    raise SystemExit(
                        "--frontier needs a model gateway — set it in Admin -> Model "
                        "gateway (or ESTIMO_GATEWAY__*)"
                    )
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as session:
                return await leave_one_out(session, client=client, frontier=args.frontier)
        finally:
            if client is not None:
                await client.aclose()
            await engine.dispose()

    result = asyncio.run(_run())
    report = render_report(result, today=args.date)
    args.report.write_text(report, encoding="utf-8")
    # The machine-readable half (evals/README.md contract: one MD + one JSON per run).
    args.report.with_suffix(".json").write_text(
        json.dumps(result.as_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(report)


if __name__ == "__main__":
    main()
