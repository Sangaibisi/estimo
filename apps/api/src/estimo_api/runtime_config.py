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
from pydantic import SecretStr
from sqlalchemy import DateTime, String, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from estimo_core.secrets import MASTER_KEY_ENV, SealedSecretError, unseal
from estimo_gateway import GatewayClient, GatewayConfig

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


def merge_gateway(
    env: GatewayConfig | None, override: dict[str, Any] | None
) -> GatewayConfig | None:
    """Effective config: env defaults with the panel's saved fields laid on top.

    Either half may be absent. The panel alone is a COMPLETE configuration (ADR-0008
    — a deployment should never need an API key in a file to start), the environment
    alone is the bootstrap path, and neither means the product runs without a model:
    `None`, which every caller already handles by degrading to its deterministic path.

    The stored api_key is SEALED; it is unsealed here, at the last moment before
    the value becomes a SecretStr inside the config object.

    An unreadable stored key (master key rotated or unset — an ops action the
    sealing module explicitly anticipates) DEGRADES to the environment key rather
    than raising. Raising here would 500 every consumer at once — including
    `GET /v1/system`, which renders the very Admin panel whose "re-enter the key"
    field and "revert to environment" button are the documented recovery path. A
    surface that breaks its own recovery route is worse than one running on the
    bootstrap key with a warning.
    """
    if not override:
        # An env gateway with an EMPTY key is not a configured gateway. `.env` files
        # routinely carry `ESTIMO_GATEWAY__API_KEY=` with nothing after it, and
        # SecretStr("") is not None — so without this the product would report itself
        # configured and fail on the first call instead of degrading cleanly.
        if env is not None and not env.api_key.get_secret_value():
            return None
        return env
    api_key = env.api_key if env else None
    if api_key is not None and not api_key.get_secret_value():
        api_key = None
    if override.get("api_key"):
        try:
            api_key = SecretStr(unseal(override["api_key"]))
        except SealedSecretError:
            logger.error(
                "stored gateway api_key could not be unsealed (%s rotated or unset); "
                "falling back to the environment key — re-enter it in Admin → Model gateway",
                MASTER_KEY_ENV,
            )
    base_url = override.get("base_url") or (str(env.base_url) if env else None)
    # A gateway without an endpoint or without a credential is not a half-configured
    # gateway, it is an unconfigured one. Saying so is what lets every consumer take
    # its documented degraded path instead of constructing a client that cannot work.
    if not base_url or api_key is None or not api_key.get_secret_value():
        return None
    merged: dict[str, Any] = {
        "base_url": base_url,
        "api_key": api_key,
        "max_retries": override.get("max_retries", env.max_retries if env else 2),
        "timeout_seconds": override.get("timeout_seconds", env.timeout_seconds if env else 120.0),
        "connect_timeout_seconds": override.get(
            "connect_timeout_seconds", env.connect_timeout_seconds if env else 5.0
        ),
        # .get with a default, NOT `or`: `or` would resurrect the env profiles the
        # moment an operator deliberately cleared every row.
        "profiles": override.get("profiles", env.profiles if env else {}),
    }
    return GatewayConfig(**merged)


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
