"""Admin → System: runtime configuration readout, edit, and a live gateway check.

ADR-0006 made the environment the only config source; ADR-0008 amends it for
OPERATOR settings: the gateway (URL, key, stage→profile routing, timeouts) is
editable here and stored in `runtime_settings`, overriding the env defaults per
field, effective immediately. Bootstrap values stay env-only — database URLs, OIDC
(a bad save there would lock every admin out of the very panel that could fix it),
CORS, and the ESTIMO_SECRET_KEY that seals stored secrets.

Redaction contract, unchanged in both directions: secrets are reduced to presence
booleans on the way out (key values never serialize, URL userinfo is stripped) and
sealed on the way in before they touch the database.
"""

from __future__ import annotations

import time
from importlib.metadata import version
from typing import Annotated, Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, SecretStr, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from estimo_api.db import get_session
from estimo_api.runtime_config import (
    effective_gateway,
    gateway_key_readable,
    invalidate_gateway_cache,
    merge_gateway,
    read_gateway_override,
    write_gateway_override,
)
from estimo_core.secrets import encryption_available, seal
from estimo_gateway import GatewayClient, GatewayConfig, GatewayError
from estimo_gateway.client import (
    GatewayConnectionError,
    GatewayRateLimitedError,
    GatewayStatusError,
    UnknownStageError,
)

router = APIRouter(prefix="/v1", tags=["system"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _display_url(url: str) -> str:
    """A URL safe to show: scheme/host/port/path only, userinfo dropped.

    Operators do front gateways with basic-auth reverse proxies and put the
    credential in the URL — `str(HttpUrl)` preserves it, so serializing the raw
    value would hand the proxy password to every admin page load.
    """
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))


def _sanitized_gateway_error(exc: GatewayError) -> str:
    """A failure reason that is OURS, never the upstream's.

    `GatewayStatusError` (and the 429 subclass) embed the gateway's entire error
    body via the OpenAI client — and a misconfigured proxy happily echoes the API
    key it was shown back into that body. Upstream-authored text therefore never
    passes through; we report the status code and our own words.
    """
    if isinstance(exc, GatewayRateLimitedError):
        return "gateway rate-limited the request (HTTP 429 after client retries)"
    if isinstance(exc, GatewayStatusError):
        return f"gateway returned HTTP {exc.status_code} (upstream error body withheld)"
    if isinstance(exc, UnknownStageError | GatewayConnectionError):
        # Locally-authored messages: the profile-routing explanation, or httpx's
        # generic "Connection error." — no upstream content in either.
        return str(exc)
    return f"gateway call failed: {type(exc).__name__}"


def _gateway_view(
    config: Any, *, source: str, key_readable: bool = True, env_present: bool = False
) -> dict[str, Any]:
    """The one redacted serialization of gateway config (GET and PUT share it).

    `config is None` is a real, expected state — a fresh deployment that has not been
    given a model endpoint yet (ADR-0008/0009: the gateway is panel-managed, and the
    API boots without it). The panel renders "not configured" from `configured: false`
    rather than from a missing field, so nothing downstream has to guess.
    """
    if config is None:
        return {
            "configured": False,
            "base_url": None,
            "api_key_present": False,
            "profiles": {},
            "timeout_seconds": None,
            "connect_timeout_seconds": None,
            "max_retries": None,
            "source": source,
            # Is there an environment gateway UNDERNEATH the override? Decides whether
            # dropping the panel override reverts to something or removes the gateway.
            "env_present": env_present,
            "secrets_encrypted": encryption_available(),
            "stored_key_readable": key_readable,
        }
    return {
        "configured": True,
        "base_url": _display_url(str(config.base_url)),
        "api_key_present": bool(config.api_key.get_secret_value()),
        "profiles": config.profiles,
        "timeout_seconds": config.timeout_seconds,
        "connect_timeout_seconds": config.connect_timeout_seconds,
        "max_retries": config.max_retries,
        # "panel" = a runtime_settings override is active; "environment" = pure env.
        "source": source,
        "env_present": env_present,
        # False = stored secrets carry a legible plain: prefix; the panel shows a
        # warning telling the operator to set ESTIMO_SECRET_KEY.
        "secrets_encrypted": encryption_available(),
        # False = a key IS stored but will not unseal (master key rotated/unset), so
        # calls are running on the environment key. Visible, never silent.
        "stored_key_readable": key_readable,
    }


@router.get("/system")
async def system_info(request: Request, session: SessionDep) -> dict[str, Any]:
    """Everything an operator needs to verify a deployment, nothing an attacker wants.

    The database URL is deliberately reduced to host/name/role: the DSN carries a
    password. `api_key_present` is a boolean for the same reason.
    """
    settings = request.app.state.settings
    auth = settings.auth
    db = settings.database_url
    override = await read_gateway_override(session)
    gateway = merge_gateway(settings.gateway, override)
    gateway_source = "panel" if override else ("environment" if settings.gateway else "unset")

    return {
        "version": version("estimo-api"),
        "auth": {
            "mode": "oidc" if auth.enabled else "open",
            "issuer": auth.issuer or None,
            "audience": auth.audience or None,
            "role_claim": auth.role_claim,
            "tenant_claim": auth.tenant_claim,
            # Empty = the ACL clamp can attribute no audience and falls back to
            # public-only. Worth surfacing loudly: it silently narrows retrieval.
            "acl_claim": auth.acl_claim or None,
        },
        "gateway": _gateway_view(
            gateway,
            # "unset" is its own answer: neither the panel nor the environment has
            # one. Reporting "environment" there would name a source that holds
            # nothing, and an operator would go looking in the wrong place.
            source=gateway_source,
            key_readable=gateway_key_readable(override),
            env_present=settings.gateway is not None,
        ),
        "database": {
            "host": db.hosts()[0]["host"] if db.hosts() else None,
            "name": (db.path or "/").lstrip("/") or None,
            "role": db.hosts()[0]["username"] if db.hosts() else None,
        },
        "cors_origins": settings.cors_origins,
    }


class GatewayOverrideIn(BaseModel):
    """The panel's gateway form (ADR-0008). Absent field = fall back to the env
    default. `api_key` is WRITE-ONLY: absent keeps whatever is already stored,
    `clear_api_key` drops it back to the env key. `reset` drops the whole override.
    """

    reset: bool = False
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, min_length=1, max_length=500)
    clear_api_key: bool = False
    profiles: dict[str, str] | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)
    connect_timeout_seconds: float | None = Field(default=None, gt=0)
    max_retries: int | None = Field(default=None, ge=0, le=10)


def _sanitized_422(exc: ValidationError) -> HTTPException:
    """loc + msg only — never the offending value.

    Body-shape errors are handled app-wide (see the RequestValidationError handler in
    main.py); this covers the SECOND validation, where the merged GatewayConfig is
    constructed from an already-parsed document.
    """
    errors = "; ".join(
        f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in exc.errors()
    )
    return HTTPException(status_code=422, detail=f"invalid gateway settings — {errors}")


@router.put("/system/gateway")
async def put_gateway_override(
    request: Request, session: SessionDep, body: GatewayOverrideIn
) -> dict[str, Any]:
    """Save the panel's gateway settings. Takes effect immediately — no restart.

    The document is validated by CONSTRUCTING the merged GatewayConfig before
    anything is written, so a typo'd URL is a 422, never a saved outage.
    """
    settings = request.app.state.settings
    if body.reset:
        await write_gateway_override(session, None)
        invalidate_gateway_cache(request)
        return _gateway_view(
            settings.gateway,
            source="environment" if settings.gateway else "unset",
            env_present=settings.gateway is not None,
        )

    # PATCH semantics over the STORED document, not a rebuild from the body.
    #
    # The body carries only the fields the operator changed — the panel deliberately
    # omits an unchanged base_url, because the value in that field came from
    # /v1/system with userinfo stripped and echoing it back would persist a redacted
    # URL over a working one. Rebuilding `doc` from the body therefore DELETED the
    # endpoint on every save after the first: change a timeout, lose the gateway.
    existing = await read_gateway_override(session) or {}
    doc: dict[str, Any] = dict(existing)
    if body.base_url is not None:
        doc["base_url"] = body.base_url
    if body.api_key is not None:
        doc["api_key"] = seal(body.api_key)
    elif body.clear_api_key:
        doc.pop("api_key", None)
    if body.profiles is not None:
        doc["profiles"] = body.profiles
    if body.timeout_seconds is not None:
        doc["timeout_seconds"] = body.timeout_seconds
    if body.connect_timeout_seconds is not None:
        doc["connect_timeout_seconds"] = body.connect_timeout_seconds
    if body.max_retries is not None:
        doc["max_retries"] = body.max_retries

    # Validate the ENDPOINT itself, always — not only when a full config happens to
    # be constructible. merge_gateway returns None for a gateway with no credential,
    # which used to skip the only check a panel-supplied URL ever got, so a typo was
    # persisted with HTTP 200 and surfaced later as a 500 from a different request.
    if doc.get("base_url"):
        try:
            GatewayConfig(base_url=doc["base_url"], api_key=SecretStr("validation-only"))
        except ValidationError as exc:
            raise _sanitized_422(exc) from exc
    try:
        merged = merge_gateway(settings.gateway, doc)
    except ValidationError as exc:
        raise _sanitized_422(exc) from exc

    await write_gateway_override(session, doc or None)
    invalidate_gateway_cache(request)
    return _gateway_view(
        merged,
        source="panel" if doc else ("environment" if settings.gateway else "unset"),
        env_present=settings.gateway is not None,
    )


@router.post("/system/gateway-check")
async def gateway_check(request: Request, session: SessionDep) -> dict[str, Any]:
    """One real round-trip through the EFFECTIVE gateway config (panel > env), timed.

    Always 200: an unreachable gateway is a *finding*, not a failed request — the
    admin screen renders `ok: false` with the reason instead of a toast. That
    contract holds for ANY failure, including a gateway that answers 200 with a
    body the client cannot parse — hence the broad catch below.
    """
    config = await effective_gateway(request, session)
    if config is None:
        # Not a failure of the gateway — there is no gateway. Same 200 contract, and
        # the panel shows the same "reason" line it shows for a refused connection.
        return {
            "ok": False,
            "latency_ms": 0,
            # A CODE as well as a sentence: the panel is bilingual, and an English
            # string invented by the API cannot be translated by the screen that
            # renders it. The sentence stays for API/CLI callers.
            "reason": "not-configured",
            "error": "no model gateway is configured",
        }
    client = GatewayClient(config)
    try:
        started = time.perf_counter()
        try:
            result = await client.complete(
                "smoke",
                [{"role": "user", "content": "Reply with exactly: ok"}],
                max_tokens=16,
            )
            # Read the clock before pool teardown; aclose() is not the gateway's
            # latency and must not be billed to it.
            latency_ms = round((time.perf_counter() - started) * 1000)
        except GatewayError as exc:
            return {
                "ok": False,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "error": _sanitized_gateway_error(exc),
            }
        except Exception as exc:  # noqa: BLE001 - diagnostic endpoint; always 200
            return {
                "ok": False,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                # Unknown failure => unknown content; expose the type, not the text.
                "error": f"unexpected {type(exc).__name__} while calling the gateway",
            }
    finally:
        await client.aclose()
    return {"ok": True, "model": result.model, "latency_ms": latency_ms}
