"""Admin → System: the redacted runtime configuration, and a live gateway check.

Estimo is configured ONLY through environment variables (ADR-0006), which is right
for security and wrong for discoverability: an operator standing the stack up has no
way to see, from the product, which gateway it talks to, whether a key is present,
or how stages route to model profiles — the design's Admin screen promises exactly
that table (docs/design/README.md, "UI contract for the gateway routing profiles").

This surface closes the gap without weakening the rule: it REPORTS configuration,
it never accepts it. Secrets are reduced to presence booleans; the key value never
leaves the process. Changing anything still means changing the environment and
restarting — which is the auditable path we want operators on.
"""

from __future__ import annotations

import time
from importlib.metadata import version
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Request

from estimo_gateway import GatewayClient, GatewayError
from estimo_gateway.client import (
    GatewayConnectionError,
    GatewayRateLimitedError,
    GatewayStatusError,
    UnknownStageError,
)

router = APIRouter(prefix="/v1", tags=["system"])


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


@router.get("/system")
async def system_info(request: Request) -> dict[str, Any]:
    """Everything an operator needs to verify a deployment, nothing an attacker wants.

    The database URL is deliberately reduced to host/name/role: the DSN carries a
    password. `api_key_present` is a boolean for the same reason.
    """
    settings = request.app.state.settings
    gateway = settings.gateway
    auth = settings.auth
    db = settings.database_url

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
        "gateway": {
            "base_url": _display_url(str(gateway.base_url)),
            "api_key_present": bool(gateway.api_key.get_secret_value()),
            "profiles": gateway.profiles,
            "timeout_seconds": gateway.timeout_seconds,
            "max_retries": gateway.max_retries,
        },
        "database": {
            "host": db.hosts()[0]["host"] if db.hosts() else None,
            "name": (db.path or "/").lstrip("/") or None,
            "role": db.hosts()[0]["username"] if db.hosts() else None,
        },
        "cors_origins": settings.cors_origins,
    }


@router.post("/system/gateway-check")
async def gateway_check(request: Request) -> dict[str, Any]:
    """One real round-trip through the configured gateway, timed.

    Always 200: an unreachable gateway is a *finding*, not a failed request — the
    admin screen renders `ok: false` with the reason instead of a toast. That
    contract holds for ANY failure, including a gateway that answers 200 with a
    body the client cannot parse — hence the broad catch below.
    """
    settings = request.app.state.settings
    client = GatewayClient(settings.gateway)
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
