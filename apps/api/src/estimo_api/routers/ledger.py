"""Ledger & analog search (design screen 7): read-only views over the estimate ledger.

The screen's whole argument is the outside view — what similar past work actually
cost — so every row carries the estimate given, the actual, and the deviation, and
search runs through the same Turkish hybrid retrieval the estimator uses.
"""

from __future__ import annotations

from typing import Annotated, Any

from estimo_knowledge import LedgerEntryRow, find_analogs
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimo_api.db import get_session

router = APIRouter(prefix="/v1/ledger", tags=["ledger"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _row(row: LedgerEntryRow) -> dict[str, Any]:
    likely = float(row.est_likely) if row.est_likely is not None else None
    single = float(row.estimate_single) if row.estimate_single is not None else None
    estimate = likely if likely is not None else single
    actual = float(row.actual_effort) if row.actual_effort is not None else None
    return {
        "id": str(row.id),
        "brd_ref": row.brd_ref,
        "item_title": row.item_title,
        "module_tags": list(row.module_tags or ()),
        "team": row.team,
        "estimate": (
            {
                "optimistic": float(row.est_optimistic) if row.est_optimistic is not None else None,
                "likely": likely,
                "pessimistic": (
                    float(row.est_pessimistic) if row.est_pessimistic is not None else None
                ),
                "single": single,
            }
        ),
        "actual_effort": actual,
        "actual_source": row.actual_source,
        "scope_changed": row.scope_changed,
        "deviation": round(actual / estimate, 2) if actual is not None and estimate else None,
        "origin": "product" if row.origin_ref else "imported",
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


@router.get("")
async def list_ledger(
    session: SessionDep,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    """Browse the ledger, or search it through the analog retrieval path.

    An empty query lists the newest entries; a query returns the ranked analog set
    the estimator would see, so the screen and the estimator agree by construction.
    """
    summary = (
        await session.execute(
            select(
                func.count(LedgerEntryRow.id),
                func.count(LedgerEntryRow.actual_effort),
            )
        )
    ).one()

    if q.strip():
        cards = await find_analogs(session, q, limit=limit)
        ids = [card.entry_id for card in cards]
        rows = {
            row.id: row
            for row in (
                await session.execute(select(LedgerEntryRow).where(LedgerEntryRow.id.in_(ids)))
            ).scalars()
        }
        entries = [_row(rows[i]) for i in ids if i in rows]
    else:
        result = await session.execute(
            select(LedgerEntryRow).order_by(LedgerEntryRow.created_at.desc()).limit(limit)
        )
        entries = [_row(row) for row in result.scalars()]

    return {
        "entries": entries,
        "total": int(summary[0] or 0),
        "with_actuals": int(summary[1] or 0),
        "searched": bool(q.strip()),
    }
