"""Application factory. The async engine is created here (lazy — no socket until first
use); the lifespan builds the OIDC verifier, runs the startup janitor, and disposes."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from estimo_api.db import build_engine, build_sessionmaker
from estimo_api.mcp_server import build_mcp
from estimo_api.routers import connections, estimates, health, metrics, runs
from estimo_api.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings if settings is not None else Settings()
    # ESTIMO_LOG_LEVEL scopes to the estimo.* namespace only — a DEBUG level must never
    # flip third-party loggers (openai/httpx) into payload-logging verbosity.
    logging.basicConfig(level="INFO")
    logging.getLogger("estimo").setLevel(app_settings.log_level.upper())

    engine = build_engine(app_settings)
    sessionmaker = build_sessionmaker(engine)
    # MCP is a Starlette sub-app (streamable HTTP); build it now so it mounts before
    # the server starts, and thread its lifespan through the API's.
    mcp_app = build_mcp(sessionmaker).http_app(path="/")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = app_settings
        app.state.engine = engine
        app.state.sessionmaker = sessionmaker
        app.state.oidc_verifier = None
        if app_settings.auth.enabled:
            from estimo_api.auth import OidcVerifier

            app.state.oidc_verifier = OidcVerifier(app_settings.auth)
            logging.getLogger("estimo.api").info(
                "OIDC auth enabled (issuer=%s)", app_settings.auth.issuer
            )

        # A crashed process leaves sync runs 'running' forever, which would block every
        # future sync of those connections (S9 guard). Best-effort — startup must not
        # hinge on the DB being reachable this instant (readiness is /readyz's job).
        from estimo_connectors.sync import sweep_interrupted_runs

        try:
            async with sessionmaker() as session:
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

    app = FastAPI(title="Estimo API", lifespan=lifespan)
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
    app.include_router(metrics.router, dependencies=[Depends(require_reviewer)])
    app.include_router(connections.router)
    app.mount("/mcp", mcp_app)
    return app


def app_factory() -> FastAPI:
    """Uvicorn entrypoint: `uvicorn estimo_api.main:app_factory --factory`.

    Settings are read (and validated, failing fast) at process start, not import time.
    """
    return create_app()
