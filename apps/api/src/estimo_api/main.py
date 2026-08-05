"""Application factory. The async engine is created here (lazy — no socket until first
use); the lifespan builds the OIDC verifier, runs the startup janitor, and disposes."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm.exc import StaleDataError

from estimo_api.db import build_engine, build_sessionmaker
from estimo_api.mcp_server import build_mcp
from estimo_api.routers import (
    connections,
    estimates,
    health,
    impact,
    ledger,
    metrics,
    runs,
    system,
)
from estimo_api.settings import Settings


class _BodyTooLarge(Exception):
    """Raised from inside the ASGI receive seam; turned into a 413 by the middleware."""


# Hard ceiling for ANY request body. The ledger import (8 MB, checked again inside the
# endpoint) is the largest legitimate payload; the headroom covers multipart framing.
MAX_REQUEST_BYTES = 12 * 1024 * 1024

# Hosts that mean "nobody configured this": the RFC 2606 .invalid TLD can never
# resolve, so a value carrying it is a leftover template, not an endpoint.
PLACEHOLDER_GATEWAY_SUFFIX = ".invalid"


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings if settings is not None else Settings()
    # ESTIMO_LOG_LEVEL scopes to the estimo.* namespace only — a DEBUG level must never
    # flip third-party loggers (openai/httpx) into payload-logging verbosity.
    logging.basicConfig(level="INFO")
    logging.getLogger("estimo").setLevel(app_settings.log_level.upper())

    engine = build_engine(app_settings)
    sessionmaker = build_sessionmaker(engine)
    # System (owner) sessionmaker for cross-tenant maintenance paths — falls back to
    # the app connection when no owner URL is configured (single-tenant).
    system_engine = (
        create_async_engine(str(app_settings.owner_database_url), pool_pre_ping=True)
        if app_settings.owner_database_url
        else None
    )
    system_sessionmaker = (
        build_sessionmaker(system_engine) if system_engine is not None else sessionmaker
    )
    # MCP is a Starlette sub-app (streamable HTTP); build it now so it mounts before
    # the server starts, and thread its lifespan through the API's.
    mcp_app = build_mcp(sessionmaker, app_settings.auth).http_app(path="/")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = app_settings
        app.state.engine = engine
        app.state.sessionmaker = sessionmaker
        app.state.system_sessionmaker = system_sessionmaker
        app.state.oidc_verifier = None
        if app_settings.auth.enabled:
            from estimo_api.auth import OidcVerifier

            app.state.oidc_verifier = OidcVerifier(app_settings.auth)
            logging.getLogger("estimo.api").info(
                "OIDC auth enabled (issuer=%s)", app_settings.auth.issuer
            )

        # Say at BOOT what an operator would otherwise discover inside a feature,
        # minutes later, on someone else's machine. Not an error: the product runs
        # deterministically without a model, and the gateway is panel-managed by
        # design (ADR-0008) — but "runs degraded" must never be silent.
        env_gateway = app_settings.gateway
        if env_gateway is None:
            logging.getLogger("estimo.api").info(
                "no model gateway in the environment — the API will use whatever is "
                "saved under Admin -> Model gateway; until something is, every "
                "model-assisted step degrades to its deterministic path"
            )
        elif (env_gateway.base_url.host or "").endswith(PLACEHOLDER_GATEWAY_SUFFIX):
            logging.getLogger("estimo.api").warning(
                "the model gateway points at a non-resolvable placeholder host (%s) — "
                "configure it under Admin -> Model gateway (or ESTIMO_GATEWAY__*); "
                "every model-assisted step will degrade until you do",
                env_gateway.base_url,
            )

        # A crashed process leaves sync runs 'running' forever, which would block every
        # future sync of those connections (S9 guard). Best-effort — startup must not
        # hinge on the DB being reachable this instant (readiness is /readyz's job).
        from estimo_connectors.sync import sweep_interrupted_runs

        try:
            async with system_sessionmaker() as session:
                swept = await sweep_interrupted_runs(session)
            if swept:
                logging.getLogger("estimo.api").warning(
                    "marked %d interrupted sync run(s) as failed", swept
                )
        except Exception:
            logging.getLogger("estimo.api").warning(
                "interrupted-run sweep skipped (db not ready at startup)", exc_info=True
            )

        async with AsyncExitStack() as stack:
            # Run the MCP sub-app's own lifespan (session manager) inside ours.
            await stack.enter_async_context(mcp_app.router.lifespan_context(mcp_app))
            try:
                yield
            finally:
                await engine.dispose()
                if system_engine is not None:
                    await system_engine.dispose()

    app = FastAPI(title="Estimo API", lifespan=lifespan)

    @app.exception_handler(StaleDataError)
    async def _stale_state(_request: Request, _exc: StaleDataError) -> JSONResponse:
        """Someone else changed this estimate between our read and our write.

        The workflow rewrites the whole `state` document, so the alternative to
        failing here is erasing their change and reporting success — which is what
        happened before the version column existed.
        """
        return JSONResponse(
            status_code=409,
            content={
                "detail": (
                    "this estimate changed while your request was in flight — reload and try again"
                )
            },
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        """422 without the offending INPUT echoed back.

        FastAPI's default handler serializes each failing field's value into the
        response. Since ADR-0008 lets operators paste credentials into the API
        (gateway key, connector tokens), that default turns any length/type slip
        into a credential reflected to the caller — and, through the web client's
        error banner, into the DOM and every HAR capture. Location and message are
        enough to fix a bad request; the value never is.
        """
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
                    for error in exc.errors()
                ]
            },
        )

    @app.middleware("http")
    async def _bound_request_body(request: Request, call_next: Any) -> Response:
        """Refuse an oversized body BEFORE anything reads it.

        Route dependencies — including `require_admin` — run after Starlette has
        already parsed the multipart body, and its parser spools past 1 MB to a
        temp file with no ceiling. So without this, an unauthenticated caller can
        make the server write an arbitrary amount to disk on the way to a 401, and
        the endpoint's own 8 MB cap only ever bounds the copy it makes afterwards.

        Content-Length is a claim, not a fact, so it is checked first (cheap, and it
        stops the honest case) and the streamed bytes are counted regardless.
        """
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_REQUEST_BYTES:
            return JSONResponse(status_code=413, content={"detail": "request body too large"})

        received = 0
        exceeded = False
        original = request.receive

        async def _counting_receive() -> Any:
            nonlocal received, exceeded
            message = await original()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_REQUEST_BYTES:
                    exceeded = True
                    msg = "request body too large"
                    raise _BodyTooLarge(msg)
            return message

        request._receive = _counting_receive
        try:
            response: Response = await call_next(request)
        except _BodyTooLarge:
            return JSONResponse(status_code=413, content={"detail": "request body too large"})
        # The multipart parser catches broadly, so tripping the ceiling mid-parse
        # surfaces as its own "error parsing the body" 400. The read still stopped —
        # which is the point — but the caller deserves the real reason, so the flag is
        # checked after the fact rather than trusting the exception to propagate.
        if exceeded:
            return JSONResponse(status_code=413, content={"detail": "request body too large"})
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    from fastapi import Depends

    from estimo_api.auth import require_admin, require_estimator, require_reviewer

    # Health is unauthenticated (probes). Everything else requires at least an
    # authenticated estimator when auth is enabled; sign-off and admin surfaces add
    # their own stricter role checks per route. In single-tenant (auth-disabled) mode
    # the synthetic principal holds every role, so these are no-ops.
    app.include_router(health.router)
    app.include_router(runs.router, dependencies=[Depends(require_admin)])
    app.include_router(estimates.router, dependencies=[Depends(require_estimator)])
    app.include_router(impact.router, dependencies=[Depends(require_estimator)])
    app.include_router(metrics.router, dependencies=[Depends(require_reviewer)])
    app.include_router(ledger.router, dependencies=[Depends(require_estimator)])
    # Connections/canonical READS need a reviewer at minimum; the mutating routes
    # inside carry their own stricter admin/reviewer checks. The webhook receiver is
    # HMAC-authenticated and is mounted on its own unauthenticated router below.
    app.include_router(connections.router, dependencies=[Depends(require_reviewer)])
    app.include_router(connections.webhook_router)
    # Redacted runtime config + gateway diagnostics — an operator surface, admin-only.
    app.include_router(system.router, dependencies=[Depends(require_admin)])
    app.mount("/mcp", mcp_app)
    return app


def app_factory() -> FastAPI:
    """Uvicorn entrypoint: `uvicorn estimo_api.main:app_factory --factory`.

    Settings are read (and validated, failing fast) at process start, not import time.
    """
    return create_app()
