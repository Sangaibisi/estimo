"""Runtime settings stored in the database (ADR-0008).

The environment is demoted to *bootstrap defaults*: whatever the Admin panel has
saved in `runtime_settings` overrides it, immediately and without a restart. Only
genuinely technical bootstrap values stay env-only — the database URLs, OIDC (a
mis-save there would lock every admin out of the very panel that could fix it),
CORS, and the optional ESTIMO_SECRET_KEY that seals stored secrets.

Precedence: panel (DB) > environment. Per FIELD, not per document — an operator
who only saved a base URL keeps env profiles and key.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from typing import Any

from estimo_knowledge.db import Base
from fastapi import Request
from sqlalchemy import DateTime, String, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from estimo_core.secrets import SealedSecretError, unseal
from estimo_gateway import GatewayClient, GatewayConfig

# The per-field merge itself is shared with the CLIs (estimo-embed, estimo-boe,
# estimo-pipeline) — one implementation, or the panel's semantics quietly fork.
# Re-exported: the API's routers and tests import it from here.
from estimo_gateway.runtime import merge_gateway

__all__ = ["merge_gateway"]

logger = logging.getLogger("estimo.api.runtime_config")

GATEWAY_KEY = "gateway"

# How long a worker may serve gateway config it read earlier. A save invalidates the
# cache of the worker that handled it; OTHER workers (uvicorn --workers, replicas)
# keep serving the old config for up to this long — so "save, then Test gateway" can
# land on a stale worker and report the previous endpoint. Ten seconds is chosen to
# make that window smaller than a human retry, not to eliminate it; eliminating it
# needs a notify/pubsub channel, which a single-deployment product does not warrant.
_CACHE_TTL_SECONDS = 10.0


class RuntimeSetting(Base):
    """One deployment-level setting document. GLOBAL on purpose: no tenant_id and
    no RLS — this is the infrastructure config `/v1/system` already reports
    deployment-wide, not tenant data."""

    __tablename__ = "runtime_settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


async def read_gateway_override(session: AsyncSession) -> dict[str, Any] | None:
    row = await session.scalar(select(RuntimeSetting).where(RuntimeSetting.key == GATEWAY_KEY))
    return row.value if row else None


async def write_gateway_override(session: AsyncSession, value: dict[str, Any] | None) -> None:
    row = await session.scalar(select(RuntimeSetting).where(RuntimeSetting.key == GATEWAY_KEY))
    if value is None:
        if row is not None:
            await session.delete(row)
    elif row is None:
        session.add(RuntimeSetting(key=GATEWAY_KEY, value=value))
    else:
        row.value = value
    await session.commit()


def gateway_key_readable(override: dict[str, Any] | None) -> bool:
    """False when a stored key exists but cannot be unsealed — surfaced by
    `/v1/system` so the degradation above is visible, never silent."""
    if not override or not override.get("api_key"):
        return True
    try:
        unseal(override["api_key"])
    except SealedSecretError:
        return False
    return True


def invalidate_gateway_cache(request: Request) -> None:
    request.app.state.gateway_cache = None


def gateway_client(config: GatewayConfig | None) -> GatewayClient | None:
    """Best-effort gateway client from an EFFECTIVE config (panel override > env).

    `None` when there is no usable gateway, so callers whose LLM leg is optional —
    connector distillation, the ledger's dense retrieval leg — degrade instead of
    failing: a misconfigured gateway must not take down a screen that has a
    lexical answer to give.
    """
    if config is None:
        return None
    try:
        return GatewayClient(config)
    except Exception:
        # Logged, not swallowed. A container-level httpx problem (an ALL_PROXY scheme
        # with no support installed, a missing CA bundle) fails HERE, and returning a
        # silent None made the product look like it had no gateway configured while
        # the panel insisted it did.
        logger.exception("could not construct a gateway client from the effective config")
        return None


async def effective_gateway(request: Request, session: AsyncSession) -> GatewayConfig | None:
    """The gateway config every caller should use. Cached briefly per process.

    `None` when nothing is configured anywhere — a legitimate state on a fresh
    deployment, not an error.
    """
    cached = getattr(request.app.state, "gateway_cache", None)
    now = time.monotonic()
    if cached is not None and cached[1] > now:
        config: GatewayConfig | None = cached[0]
        return config
    override = await read_gateway_override(session)
    config = merge_gateway(request.app.state.settings.gateway, override)
    request.app.state.gateway_cache = (config, now + _CACHE_TTL_SECONDS)
    return config
