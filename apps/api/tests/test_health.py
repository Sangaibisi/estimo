"""Health endpoints via in-process ASGI transport (no server, no real DB)."""

from collections.abc import AsyncIterator

import httpx
import pytest
from _helpers import make_settings
from asgi_lifespan import LifespanManager

from estimo_api.main import create_app


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    # Unreachable DB on purpose: liveness must not care, readiness must fail fast.
    app = create_app(make_settings("postgresql+asyncpg://x:x@127.0.0.1:9/void"))
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


async def test_healthz_is_dependency_free(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]


async def test_readyz_reports_unavailable_db(client: httpx.AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_settings_rejects_non_asyncpg_scheme() -> None:
    with pytest.raises(ValueError, match="asyncpg"):
        make_settings("postgresql://x:x@localhost/estimo")
