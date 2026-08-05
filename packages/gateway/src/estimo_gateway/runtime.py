"""The gateway a DEPLOYMENT actually uses: panel override first, env as bootstrap.

ADR-0008 demoted the environment to bootstrap defaults — whatever the Admin panel
saved in the global `runtime_settings` table overrides it, per FIELD. The API applies
that rule in `estimo_api.runtime_config`; every CLI that talks to the model must apply
the *same* rule, or a panel-configured deployment's CLIs keep reporting "gateway is
not configured" about a deployment whose Admin screen shows a working one. This module
is the one shared implementation (the API re-exports `merge_gateway` from here).

The DB is touched through a duck-typed SQLAlchemy AsyncEngine so this package does not
grow a database dependency: callers that have no engine pass None and get pure env
behavior.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from pydantic import SecretStr, ValidationError

from estimo_core.secrets import MASTER_KEY_ENV, SealedSecretError, unseal
from estimo_gateway.client import GatewayClient
from estimo_gateway.config import GatewayConfig, GatewaySettings

logger = logging.getLogger("estimo.gateway.runtime")


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


async def stored_gateway_override(engine: Any) -> dict[str, Any] | None:
    """The panel's saved gateway document, or None.

    `exec_driver_sql` keeps this free of a SQLAlchemy import: the engine is whatever
    AsyncEngine the caller already has. A schema without the table (pre-0011) is a
    deployment without an override, not an error.
    """
    try:
        async with engine.connect() as connection:
            result = await connection.exec_driver_sql(
                "SELECT value FROM runtime_settings WHERE key = 'gateway'"
            )
            row = result.first()
    except Exception:  # noqa: BLE001 - an old schema simply has no override
        return None
    return dict(row[0]) if row else None


async def deployment_gateway_config(engine: Any | None) -> GatewayConfig | None:
    """The config a CLI should use on this deployment. None = run deterministically.

    Reads the panel override when an engine is available, the `ESTIMO_GATEWAY__*`
    environment as the bootstrap default, and merges them per field. A missing or
    half-configured environment is tolerated the same way the API's Settings loader
    tolerates it: it is simply absent.
    """
    override = await stored_gateway_override(engine) if engine is not None else None
    env: GatewayConfig | None = None
    with contextlib.suppress(ValidationError):
        env = GatewaySettings()
    return merge_gateway(env, override)


async def deployment_gateway_client(engine: Any | None) -> GatewayClient | None:
    """`deployment_gateway_config` as a ready client; None when unconfigured."""
    config = await deployment_gateway_config(engine)
    return GatewayClient(config) if config is not None else None
