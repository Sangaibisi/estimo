"""Liveness and readiness endpoints (split on purpose — see research §5/Docker)."""

from __future__ import annotations

import asyncio
from importlib.metadata import version

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: process-only, touches no dependencies."""
    return {"status": "ok", "version": version("estimo-api")}


@router.get("/readyz")
async def readyz(request: Request, response: Response) -> dict[str, str]:
    """Readiness: one pooled connection, strict 1s budget — a saturated pool must
    fail fast, not hang."""
    engine: AsyncEngine = request.app.state.engine
    try:
        async with asyncio.timeout(1.0):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
    except (TimeoutError, OSError, Exception):  # noqa: BLE001 - readiness must never raise
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable"}
    return {"status": "ready"}
