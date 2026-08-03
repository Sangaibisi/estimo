"""Honesty dashboards data (S8-3) + DORA-style second-order signals (S8-6).

Every number here is either measured or absent — no synthetic placeholder values.
Small-sample caveat is structural: sample counts ride along with every rate so the UI
can label noisy figures (coverage at ±5% needs ~100 points — web-verified).
"""

from __future__ import annotations

import statistics
from typing import Annotated, Any

from estimo_estimate import rolling_coverage, transfer_distribution
from estimo_knowledge import CalibrationSnapshot, LedgerEntryRow
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimo_api.db import get_session
from estimo_api.estimates_models import EstimateRecord, UiEvent

router = APIRouter(prefix="/v1/metrics", tags=["metrics"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def _calibration(session: AsyncSession) -> dict[str, Any]:
    snapshots = list(
        (
            await session.execute(
                select(CalibrationSnapshot)
                .order_by(CalibrationSnapshot.created_at.desc())
                .limit(30)
            )
        ).scalars()
    )
    series = [
        {
            "at": snap.created_at.isoformat(),
            "samples": snap.samples,
            "prior_based": snap.prior_based,
            "q10": float(snap.q10),
            "q50": float(snap.q50),
            "q90": float(snap.q90),
            "nominal": float(snap.nominal),
            "rolling_coverage": (
                float(snap.rolling_coverage) if snap.rolling_coverage is not None else None
            ),
        }
        for snap in reversed(snapshots)
    ]
    # The loop snapshots on every actual, so the latest snapshot IS the current
    # state — recomputing transfer_distribution live would run one hybrid search
    # per completed ledger row on every dashboard load. Compute live only before
    # the first snapshot exists.
    if series:
        latest = series[-1]
        current = {key: latest[key] for key in ("samples", "prior_based", "q10", "q50", "q90")}
    else:
        distribution = await transfer_distribution(session)
        current = {
            "samples": distribution.samples,
            "prior_based": distribution.prior_based,
            "q10": distribution.q10,
            "q50": distribution.q50,
            "q90": distribution.q90,
        }
    current["rolling_coverage"] = await rolling_coverage(session)
    return {"current": current, "series": series}


async def _product_accuracy(session: AsyncSession) -> dict[str, Any]:
    """Coverage + MAE over rows the PRODUCT estimated (origin_ref) with actuals.

    The naive baseline is the global median of completed ledger actuals — the number
    a team quoting "a typical item" would give (PRINCIPLES #7 requires the naive
    comparison next to every accuracy claim).
    """
    completed = [
        float(actual)
        for (actual,) in await session.execute(
            select(LedgerEntryRow.actual_effort).where(
                LedgerEntryRow.actual_effort.is_not(None),
                LedgerEntryRow.scope_changed.is_(False),
            )
        )
    ]
    naive = statistics.median(completed) if completed else None

    rows = (
        await session.execute(
            select(
                LedgerEntryRow.est_optimistic,
                LedgerEntryRow.est_likely,
                LedgerEntryRow.est_pessimistic,
                LedgerEntryRow.actual_effort,
            ).where(
                LedgerEntryRow.origin_ref.is_not(None),
                LedgerEntryRow.actual_effort.is_not(None),
                LedgerEntryRow.scope_changed.is_(False),
            )
        )
    ).all()
    covered = 0
    product_errors: list[float] = []
    naive_errors: list[float] = []
    for opt, likely, pess, actual in rows:
        actual_f = float(actual)
        if opt is not None and pess is not None and float(opt) <= actual_f <= float(pess):
            covered += 1
        if likely is not None:
            product_errors.append(abs(float(likely) - actual_f))
        if naive is not None:
            naive_errors.append(abs(naive - actual_f))
    samples = len(rows)
    return {
        "samples": samples,
        "coverage": round(covered / samples, 3) if samples else None,
        "nominal": 0.8,
        "mae_product": round(statistics.mean(product_errors), 2) if product_errors else None,
        "mae_naive_median": round(statistics.mean(naive_errors), 2) if naive_errors else None,
    }


async def _anchoring(session: AsyncSession) -> dict[str, Any]:
    deltas = [
        float(delta)
        for (delta,) in await session.execute(
            select(UiEvent.payload["delta_likely"].as_float()).where(
                UiEvent.kind == "draft-revealed",
                UiEvent.payload["delta_likely"].as_float().is_not(None),
            )
        )
        if delta is not None
    ]
    if not deltas:
        return {"samples": 0, "mean_abs_delta": None, "zero_delta_share": None}
    zero = sum(1 for delta in deltas if abs(delta) < 0.5)
    return {
        "samples": len(deltas),
        "mean_abs_delta": round(statistics.mean(abs(d) for d in deltas), 2),
        # A high share of near-zero deltas across estimators is the anchoring smell:
        # independent bands converging onto the (still hidden) AI number is expected
        # to be RARE when independence is real.
        "zero_delta_share": round(zero / len(deltas), 3),
    }


async def _workflow(session: AsyncSession) -> dict[str, Any]:
    # Answers presence is testable in SQL — pulling every estimate's full
    # pipeline-state JSONB just for that would grow linearly with history.
    has_answers = func.coalesce(EstimateRecord.state["answers"], func.jsonb_build_object()) != (
        func.jsonb_build_object()
    )
    records = (
        await session.execute(
            select(EstimateRecord.status, EstimateRecord.boe_version, has_answers)
        )
    ).all()
    total = len(records)
    if not total:
        return {
            "estimates": 0,
            "wip": 0,
            "question_revision_rate": None,
            "rebuild_share": None,
        }
    wip = sum(1 for status, _, _ in records if status != "boe_draft")
    revised = sum(1 for _, _, answered in records if answered)
    rebuilt = sum(1 for _, version, _ in records if (version or 0) > 1)
    return {
        "estimates": total,
        # DORA-style second-order guards (S8-6): WIP and rework must not balloon
        # while draft speed improves.
        "wip": wip,
        "question_revision_rate": round(revised / total, 3),
        "rebuild_share": round(rebuilt / total, 3),
    }


async def _attribution(session: AsyncSession) -> dict[str, Any]:
    """How much of the ledger the product itself wrote can be sliced.

    Team and domain arrive only if whoever records the actual supplies them, and the
    field is optional — so "attribution shipped" and "attribution arrives" are
    different claims. This reports the second one. Calibration slices need
    MIN_SAMPLES rows PER slice; a high unattributed count is the honest reason a
    team curve does not exist yet, and without this number that would look like a
    missing feature rather than missing data.
    """
    rows = (
        await session.execute(
            select(LedgerEntryRow.team, LedgerEntryRow.domain_tags).where(
                LedgerEntryRow.origin_ref.is_not(None)
            )
        )
    ).all()
    if not rows:
        return {"product_rows": 0, "with_team": 0, "with_domain": 0, "teams": []}
    teams = sorted({team for team, _ in rows if team})
    return {
        "product_rows": len(rows),
        "with_team": sum(1 for team, _ in rows if team),
        "with_domain": sum(1 for _, domains in rows if domains),
        "teams": teams,
    }


@router.get("/overview")
async def overview(session: SessionDep) -> dict[str, Any]:
    return {
        "calibration": await _calibration(session),
        "product_accuracy": await _product_accuracy(session),
        "anchoring": await _anchoring(session),
        "workflow": await _workflow(session),
        "attribution": await _attribution(session),
    }
