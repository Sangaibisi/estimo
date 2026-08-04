"""Honesty dashboards data (S8-3) + DORA-style second-order signals (S8-6).

Every number here is either measured or absent — no synthetic placeholder values.
Small-sample caveat is structural: sample counts ride along with every rate so the UI
can label noisy figures (coverage at ±5% needs ~100 points — web-verified).
"""

from __future__ import annotations

import datetime as dt
import itertools
import math
import statistics
from typing import Annotated, Any

from estimo_estimate import rolling_coverage, transfer_distribution
from estimo_estimate.calibration import MIN_SAMPLES
from estimo_estimate.loop import PRODUCT_ORIGIN_PREFIX
from estimo_knowledge import CalibrationSnapshot, LedgerEntryRow
from estimo_knowledge.search import ledger_slice_conditions
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimo_api.db import get_session
from estimo_api.estimates_models import (
    BoeVersionRow,
    EstimateRecord,
    IndependentEstimate,
    LineSignature,
    UiEvent,
)

router = APIRouter(prefix="/v1/metrics", tags=["metrics"])

# Below this many person-days a percentage error is dominated by rounding: a half-day
# miss on a 1 pd item is 50%. Such items are excluded from MAPE and counted, so the
# figure is never quietly averaged over items it cannot describe.
MAPE_FLOOR_PD = 2.0

# The threshold the "not distinguishable" wording is measured against.
SIGNIFICANCE_ALPHA = 0.05
# Smallest p the screen will print. Below this it says "< 0.0001" rather than rounding
# a real number to the impossible literal 0.
P_VALUE_FLOOR = 0.0001


def _binomial_tail(n: int, tail: int) -> float:
    """P(X <= tail) for X ~ Binomial(n, 0.5), summed in log space.

    Every term is exp(lgamma-based log C(n,k) - n*log 2), so nothing overflows and
    nothing underflows to a bogus zero on the way — the failure mode of the direct
    formula, which raises OverflowError at n = 1024.
    """
    log_half = math.log(0.5)
    total = 0.0
    for k in range(tail + 1):
        log_term = math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1) + n * log_half
        total += math.exp(log_term)
    return min(1.0, total)


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
            # The count THAT rate was computed from — `samples` above belongs to the
            # transfer distribution and describes a different population.
            "rolling_samples": snap.rolling_samples,
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
    rolling = await rolling_coverage(session)
    current["rolling_coverage"] = rolling.coverage if rolling else None
    # The rate travels with its count: coverage at +/-5% needs ~100 points, and the
    # rolling window is 20 by construction, so the number is never readable alone.
    current["rolling_samples"] = rolling.samples if rolling else 0
    current["min_samples"] = MIN_SAMPLES
    return {"current": current, "series": series}


# A band can only be graded when the product actually issued one. Rows without both
# edges are counted separately rather than folded into the denominator as automatic
# misses — a single-number row is not a failed range, it is not a range.
def _coverage_of(rows: list[tuple[Any, Any, Any, Any]]) -> dict[str, Any]:
    """Coverage, its sample count, and nothing when the count cannot carry a rate.

    The floor applies to the HEADLINE too, not just the per-slice bars. Before the
    screen could be sliced, the headline was the whole corpus and a thin one was
    obvious; now a reader can pick `domain=crm` from a dropdown, land on a single
    closed job, and read "we captured actuals inside the range 0% of the time" — a
    sentence about one item, printed as a verdict on the product.
    """
    banded = [(o, p, a) for o, _, p, a in rows if o is not None and p is not None]
    if not banded:
        return {"coverage": None, "samples": 0, "unbanded": len(rows), "enough": False}
    hits = sum(1 for opt, pess, actual in banded if float(opt) <= float(actual) <= float(pess))
    enough = len(banded) >= MIN_SAMPLES
    return {
        "coverage": round(hits / len(banded), 3) if enough else None,
        "samples": len(banded),
        "unbanded": len(rows) - len(banded),
        "enough": enough,
        "min_samples": MIN_SAMPLES,
    }


async def _accuracy_rows(
    session: AsyncSession,
    *,
    team: str | None = None,
    domain: str | None = None,
    months: int | None = None,
) -> list[tuple[Any, Any, Any, Any]]:
    """Product-estimated rows with actuals, optionally sliced and time-windowed."""
    conditions = [
        # LIKE 'estimate://%', not IS NOT NULL: the Jira connector writes `jira://…`
        # rows carrying a single number and no band, and grading the pipeline on those
        # would score it for estimates it never made.
        LedgerEntryRow.origin_ref.like(PRODUCT_ORIGIN_PREFIX),
        LedgerEntryRow.actual_effort.is_not(None),
        LedgerEntryRow.scope_changed.is_(False),
        *ledger_slice_conditions(team, domain),
    ]
    if months is not None:
        # completed_at is the date the WORK finished. A row without one falls out of a
        # windowed view rather than being assumed recent — `NULL >= cutoff` is NULL,
        # never true, so the comparison alone excludes them; there is no separate
        # IS NOT NULL guard because a guard that can never fire is not a guard.
        # "No rows in the last 24 months" and "no row says when it finished" are
        # different facts, which is why the unwindowed counts stay one request away.
        cutoff = dt.datetime.now(tz=dt.UTC).date() - dt.timedelta(days=int(months * 30.44))
        conditions.append(LedgerEntryRow.completed_at >= cutoff)
    result = await session.execute(
        select(
            LedgerEntryRow.est_optimistic,
            LedgerEntryRow.est_likely,
            LedgerEntryRow.est_pessimistic,
            LedgerEntryRow.actual_effort,
        ).where(*conditions)
    )
    return [(row[0], row[1], row[2], row[3]) for row in result.all()]


def _paired_verdict(product: list[float], naive: list[float]) -> dict[str, Any]:
    """Is the pipeline's error actually lower than the baseline's, or is this noise?

    The design's panel says "on this dataset the difference is not meaningful" — which
    is a claim about a test, not a feeling. This runs the cheapest defensible one: a
    two-sided sign test over the PAIRED per-item errors (each item estimated both ways,
    so the pairing is real), reported with the count of items where each side won.

    No scipy, and no float powers: the obvious `2 * sum(comb(n, k)) / 2.0**n` raises
    OverflowError the moment `n` reaches 1024 — which is not an exotic input, it is a
    tenant that has completed a thousand items, i.e. the success case. It also loses all
    precision long before that (at n≈1000 the result is already pinned to the bottom of
    the float range). The tail is summed in LOG space instead, so it is finite for any
    n and stays accurate.

    Ties (identical error) carry no information and are dropped, which is the standard
    treatment.
    """
    wins = sum(1 for p, n in zip(product, naive, strict=True) if p < n)
    losses = sum(1 for p, n in zip(product, naive, strict=True) if p > n)
    decided = wins + losses
    if decided == 0:
        return {
            "verdict": "no-signal",
            "wins": 0,
            "losses": 0,
            "p_value": None,
            "p_value_is_upper_bound": False,
        }
    p_value = min(1.0, 2.0 * _binomial_tail(decided, min(wins, losses)))
    if p_value > SIGNIFICANCE_ALPHA:
        verdict = "not-distinguishable"
    else:
        verdict = "pipeline-better" if wins > losses else "baseline-better"
    return {
        "verdict": verdict,
        "wins": wins,
        "losses": losses,
        # Rounded for display, but never rounded to a literal 0: an exact p of 3e-9 is
        # not "p = 0", and printing it as one states a certainty no test can give. Very
        # large samples also drive the log-space sum to a true underflow, so anything
        # under the floor is reported as the floor plus a flag, and the screen prints
        # "p < 0.0001".
        "p_value": max(round(p_value, 4), P_VALUE_FLOOR),
        "p_value_is_upper_bound": p_value < P_VALUE_FLOOR,
    }


async def _product_accuracy(
    session: AsyncSession,
    *,
    team: str | None = None,
    domain: str | None = None,
    months: int | None = None,
) -> dict[str, Any]:
    """Coverage + error over rows the PRODUCT estimated, against a naive baseline.

    The naive baseline is the global median of completed ledger actuals — the number
    a team quoting "a typical item" would give (PRINCIPLES #7 requires the naive
    comparison next to every accuracy claim). The baseline is deliberately NOT sliced
    or windowed with the rest: it stands for "what you would have said without us",
    and that number comes from everything the ledger knows.
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

    rows = await _accuracy_rows(session, team=team, domain=domain, months=months)
    product_errors: list[float] = []
    naive_errors: list[float] = []
    product_pct: list[float] = []
    naive_pct: list[float] = []
    for _opt, likely, _pess, actual in rows:
        actual_f = float(actual)
        if likely is None or naive is None:
            continue
        product_errors.append(abs(float(likely) - actual_f))
        naive_errors.append(abs(naive - actual_f))
        # MAPE divides by the actual, so a near-zero actual dominates the mean. Items
        # below the floor are excluded and counted, never silently averaged in.
        if actual_f >= MAPE_FLOOR_PD:
            product_pct.append(abs(float(likely) - actual_f) / actual_f)
            naive_pct.append(abs(naive - actual_f) / actual_f)

    return {
        **_coverage_of(rows),
        "nominal": 0.8,
        "mae_product": round(statistics.mean(product_errors), 2) if product_errors else None,
        "mae_naive_median": round(statistics.mean(naive_errors), 2) if naive_errors else None,
        "mape_product": round(statistics.mean(product_pct), 3) if product_pct else None,
        "mape_naive_median": round(statistics.mean(naive_pct), 3) if naive_pct else None,
        "mape_excluded": len(product_errors) - len(product_pct),
        "comparison": _paired_verdict(product_errors, naive_errors),
    }


async def _slices(session: AsyncSession) -> dict[str, Any]:
    """Per-team and per-domain coverage of the bands ESTIMO issued.

    The design draws one bar per slice and a sentence naming the worst. Both are only
    honest above a sample floor: at n=1 a bar reads 0% or 100% and says nothing about
    the slice, so a slice below MIN_SAMPLES is returned with `coverage: null` and its
    count, and the UI states the reason rather than drawing a bar.

    Slices come from the rows the product itself estimated. That is also why this can
    be empty on a deployment with a full ledger: attribution is supplied by whoever
    records the actual, and a BRD never says which team will do the work — the
    `attribution` block reports exactly that gap.
    """
    rows = (
        await session.execute(
            select(
                LedgerEntryRow.team,
                LedgerEntryRow.domain_tags,
                LedgerEntryRow.est_optimistic,
                LedgerEntryRow.est_likely,
                LedgerEntryRow.est_pessimistic,
                LedgerEntryRow.actual_effort,
            ).where(
                LedgerEntryRow.origin_ref.like(PRODUCT_ORIGIN_PREFIX),
                LedgerEntryRow.actual_effort.is_not(None),
                LedgerEntryRow.scope_changed.is_(False),
            )
        )
    ).all()
    by_team: dict[str, list[tuple[Any, Any, Any, Any]]] = {}
    by_domain: dict[str, list[tuple[Any, Any, Any, Any]]] = {}
    for team, domains, opt, likely, pess, actual in rows:
        measurement = (opt, likely, pess, actual)
        if team:
            by_team.setdefault(team, []).append(measurement)
        for domain in domains or ():
            by_domain.setdefault(domain, []).append(measurement)

    def graded(
        groups: dict[str, list[tuple[Any, Any, Any, Any]]], kind: str
    ) -> list[dict[str, Any]]:
        out = []
        for key, measurements in sorted(groups.items()):
            summary = _coverage_of(measurements)
            out.append(
                {
                    "key": key,
                    # Which dimension this is. Team and domain are both free text
                    # normalized at the same import boundary, so "billing" can be
                    # both — two rows labelled identically are two different claims.
                    "kind": kind,
                    # Withheld, not zero: a bar drawn from three jobs is a point
                    # estimate wearing a rate's clothes (PRINCIPLES #1, #6).
                    "coverage": summary["coverage"],
                    "samples": summary["samples"],
                    "unbanded": summary["unbanded"],
                    "enough": summary["enough"],
                }
            )
        return out

    return {
        "min_samples": MIN_SAMPLES,
        "teams": graded(by_team, "team"),
        "domains": graded(by_domain, "domain"),
    }


async def _anchoring(session: AsyncSession) -> dict[str, Any]:
    """How far the human band sat from the draft, and whether it was entered blind.

    The design draws two strips: bands "entered independent-first" and bands "entered
    after the draft was revealed". The second cannot mean what the design imagines —
    a band is immutable and the reveal happens BY recording it, so nobody enters a
    band having already seen the draft for that item. What CAN happen is entering one
    after the whole draft became readable another way (it is fully signed, so GET and
    the .docx serve it), and that is what `blind` records. The strips therefore read
    "recorded while the draft was hidden" and "recorded once it was readable" — a
    smaller claim than the design's, and a true one.
    """
    blind_rows = (
        await session.execute(
            select(IndependentEstimate.blind, func.count()).group_by(IndependentEstimate.blind)
        )
    ).all()
    buckets = {value: int(count) for value, count in blind_rows}
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
    entry = {
        "blind": buckets.get(True, 0),
        "after_readable": buckets.get(False, 0),
        # Recorded before the product tracked this (migration 0015). Not folded into
        # "blind": back-filling a claim about history nobody verified is how a
        # measurement becomes a decoration.
        "unknown": buckets.get(None, 0),
    }
    if not deltas:
        return {"samples": 0, "mean_abs_delta": None, "zero_delta_share": None, "entry": entry}
    zero = sum(1 for delta in deltas if abs(delta) < 0.5)
    return {
        "entry": entry,
        "samples": len(deltas),
        "mean_abs_delta": round(statistics.mean(abs(d) for d in deltas), 2),
        # A high share of near-zero deltas across estimators is the anchoring smell:
        # independent bands converging onto the (still hidden) AI number is expected
        # to be RARE when independence is real.
        "zero_delta_share": round(zero / len(deltas), 3),
    }


ANSWER_EVIDENCE_PREFIX = "answer://"

# Fewer estimates than this and an aggregate stops being an aggregate: with one
# contributing estimate, "61% of answers moved a line" is that estimate's own diff
# wearing a corpus-wide label.
MIN_QUESTION_IMPACT_ESTIMATES = 2


async def _readable_versions(session: AsyncSession) -> set[tuple[Any, int]]:
    """(estimate_id, version) pairs whose every line was signed by a reviewer.

    The same test `GET /v1/estimates/{id}/versions` applies before it will serve a
    diff. Computed once for the whole corpus rather than per estimate: the dashboard
    is a read, and the alternative is one query per version.
    """
    signed = (
        await session.execute(
            select(
                LineSignature.estimate_id,
                LineSignature.boe_version,
                LineSignature.work_item_id,
            ).distinct()
        )
    ).all()
    signed_items: dict[tuple[Any, int], set[str]] = {}
    for estimate_id, version, item_id in signed:
        signed_items.setdefault((estimate_id, version), set()).add(item_id)

    versions = (
        await session.execute(
            select(BoeVersionRow.estimate_id, BoeVersionRow.version, BoeVersionRow.document)
        )
    ).all()
    readable: set[tuple[Any, int]] = set()
    for estimate_id, version, document in versions:
        line_ids = {line["work_item_id"] for line in document.get("lines", [])}
        if line_ids and line_ids <= signed_items.get((estimate_id, version), set()):
            readable.add((estimate_id, version))
    return readable


def _lines_by_item(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {line["work_item_id"]: line for line in document.get("lines", [])}


def _answer_uris(line: dict[str, Any]) -> set[str]:
    return {
        ref["uri"]
        for ref in line.get("evidence", [])
        if str(ref.get("uri", "")).startswith(ANSWER_EVIDENCE_PREFIX)
    }


async def _question_impact(session: AsyncSession) -> dict[str, Any]:
    """Did answering a question actually move a line, and by how much?

    Measured by comparing consecutive FROZEN BoE versions (S12-5) and attributing a
    move only to lines that gained an `answer://` evidence URI at that version — a
    rebuild re-estimates everything, so a line that moved without a new answer moved
    for some other reason and is not this panel's business.

    Two exclusions that decide whether the figure is honest:

    - A line that did not exist at the previous version is counted separately as
      `lines_created`, never as a range that changed. An answer that unblocks a
      requirement CREATES a work item; there is no prior range, and folding those in
      would inflate the numerator with divisions by nothing.
    - The population is answers that landed while a draft already existed. The gate
      refuses to build over an open question by design (PRINCIPLES #3), so most
      answers arrive BEFORE any first draft and have no before-image at all. That
      count is reported rather than hidden, because it is the reason the rate is thin.
    """
    readable = await _readable_versions(session)
    rows = (
        await session.execute(
            select(
                BoeVersionRow.estimate_id, BoeVersionRow.version, BoeVersionRow.document
            ).order_by(BoeVersionRow.estimate_id, BoeVersionRow.version)
        )
    ).all()
    by_estimate: dict[Any, list[tuple[int, dict[str, Any]]]] = {}
    for estimate_id, version, document in rows:
        # Only versions whose every line carried a reviewer's signature. GET
        # /{id}/versions withholds even the DIRECTION a line moved for anything
        # short of that, because a line's three points scale with the same analog
        # median — and an aggregate over one estimate IS that estimate's direction.
        # This screen is reachable by a reviewer, the exact role the desk gate
        # applies to, so it obeys the same rule rather than becoming its bypass.
        if (estimate_id, version) in readable:
            by_estimate.setdefault(estimate_id, []).append((version, document))

    moved = 0
    unchanged = 0
    created = 0
    width_changes: list[float] = []
    for versions in by_estimate.values():
        for (older_v, older), (newer_v, newer) in itertools.pairwise(versions):
            if newer_v != older_v + 1:
                continue  # a gap means a snapshot is missing; do not diff across it
            before = _lines_by_item(older)
            for item_id, line in _lines_by_item(newer).items():
                fresh = _answer_uris(line) - _answer_uris(before.get(item_id, {}))
                if not fresh:
                    continue
                previous = before.get(item_id)
                if previous is None:
                    created += 1
                    continue
                old_range = previous["range"]
                new_range = line["range"]
                old_width = float(old_range["pessimistic"]) - float(old_range["optimistic"])
                new_width = float(new_range["pessimistic"]) - float(new_range["optimistic"])
                if (
                    old_range["optimistic"] == new_range["optimistic"]
                    and old_range["pessimistic"] == new_range["pessimistic"]
                    and old_range["likely"] == new_range["likely"]
                ):
                    unchanged += 1
                    continue
                moved += 1
                if old_width > 0:
                    width_changes.append((new_width - old_width) / old_width)

    measured = moved + unchanged
    enough = len(by_estimate) >= MIN_QUESTION_IMPACT_ESTIMATES
    return {
        "samples": measured,
        "estimates": len(by_estimate),
        "min_estimates": MIN_QUESTION_IMPACT_ESTIMATES,
        "changed_share": round(moved / measured, 3) if measured and enough else None,
        "median_width_change": (
            round(statistics.median(width_changes), 3) if width_changes and enough else None
        ),
        # Answers that produced a line rather than moving one — reported so the
        # denominator above is legible instead of looking small for no reason.
        "lines_created": created,
        "reasons": await _question_reasons(session),
    }


async def _question_reasons(session: AsyncSession) -> list[dict[str, Any]]:
    """Which ambiguity rules actually raise the questions people answer.

    Read from `issue_codes` frozen on the question at ASK time. Not from the
    requirement's current issues: the gate re-scores a requirement once its answer is
    folded in, so the live issues describe the state AFTER the question did its job —
    `missing-acceptance-criteria` disappears from the very requirement whose question
    was raised for missing acceptance criteria.
    """
    documents = (
        await session.execute(
            select(
                BoeVersionRow.estimate_id, BoeVersionRow.version, BoeVersionRow.document
            ).order_by(BoeVersionRow.estimate_id, BoeVersionRow.version)
        )
    ).all()
    # Keyed by (estimate, question) — a gate question's id is derived from the BRD's
    # own requirement code (`Q-REQ-G-04`), and two BRDs that number their requirements
    # the same way produce the same ids. Keying on the id alone silently collapsed
    # them into one survivor and undercounted every reason.
    latest: dict[tuple[Any, str], dict[str, Any]] = {}
    for estimate_id, _version, document in documents:
        for question in document.get("questions", []):
            latest[(estimate_id, str(question.get("id")))] = question
    counts: dict[str, int] = {}
    answered = 0
    for question in latest.values():
        if question.get("status") not in ("answered", "applied"):
            continue
        answered += 1
        for code in question.get("issue_codes") or ():
            # `vague-terms:kelime,kelime` carries its matches; the rule is the part
            # before the colon, or every wording becomes its own bar.
            counts[str(code).split(":", 1)[0]] = counts.get(str(code).split(":", 1)[0], 0) + 1
    return [
        {"code": code, "count": count, "share": round(count / answered, 3) if answered else None}
        for code, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    ]


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
                # Rows Estimo itself wrote, which are the only ones a user could have
                # attributed. `origin_ref IS NOT NULL` also matches `jira://…` rows the
                # connector imports, and those inflate the denominator with rows nobody
                # was ever asked to attribute — making the gap look like user apathy
                # rather than an untouched import.
                LedgerEntryRow.origin_ref.like("estimate://%")
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
async def overview(
    session: SessionDep,
    team: Annotated[str, Query(max_length=80)] = "",
    domain: Annotated[str, Query(max_length=60)] = "",
    months: Annotated[int | None, Query(ge=1, le=240)] = None,
) -> dict[str, Any]:
    """Every number here is measured or absent (module docstring), and every rate
    carries the count it was computed from.

    The slice and the window narrow the HEADLINE accuracy block. They do not narrow
    the naive baseline (that is "what you would have said without us", drawn from
    everything the ledger knows) and they do not narrow the per-slice bars, which
    already need every row they can get to clear the sample floor.
    """
    return {
        "calibration": await _calibration(session),
        "product_accuracy": await _product_accuracy(
            session, team=team or None, domain=domain or None, months=months
        ),
        "slices": await _slices(session),
        "anchoring": await _anchoring(session),
        "question_impact": await _question_impact(session),
        "workflow": await _workflow(session),
        "attribution": await _attribution(session),
        "window": {"months": months, "team": team or None, "domain": domain or None},
    }
