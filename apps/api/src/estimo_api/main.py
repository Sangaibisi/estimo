"""Application factory. Anything that opens sockets lives inside the lifespan."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from estimo_api.db import build_engine, build_sessionmaker
from estimo_api.routers import connections, estimates, health, metrics, runs
from estimo_api.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings if settings is not None else Settings()
    # ESTIMO_LOG_LEVEL scopes to the estimo.* namespace only — a DEBUG level must never
    # flip third-party loggers (openai/httpx) into payload-logging verbosity.
    logging.basicConfig(level="INFO")
    logging.getLogger("estimo").setLevel(app_settings.log_level.upper())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = build_engine(app_settings)
        app.state.settings = app_settings
        app.state.engine = engine
        app.state.sessionmaker = build_sessionmaker(engine)
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
    app.include_router(health.router)
    app.include_router(runs.router)
    app.include_router(estimates.router)
    app.include_router(metrics.router)
    app.include_router(connections.router)
    return app


def app_factory() -> FastAPI:
    """Uvicorn entrypoint: `uvicorn estimo_api.main:app_factory --factory`.

    Settings are read (and validated, failing fast) at process start, not import time.
    """
    return create_app()
