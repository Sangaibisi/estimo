"""Run-record CRUD against a real PostgreSQL (marked `db`; needs ESTIMO_TEST_DATABASE_URL)."""

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
from _helpers import make_settings
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager

from estimo_api.main import create_app

pytestmark = pytest.mark.db

ALEMBIC_INI = Path(__file__).parents[1] / "alembic.ini"


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    url = os.environ["ESTIMO_TEST_DATABASE_URL"]  # guarded by the db marker skip in root conftest
    os.environ["ESTIMO_DATABASE_URL"] = url
    command.upgrade(Config(str(ALEMBIC_INI)), "head")
    yield url


@pytest.fixture
async def client(database_url: str) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(make_settings(database_url))
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


async def test_run_lifecycle(client: httpx.AsyncClient) -> None:
    created = await client.post("/v1/runs", json={"kind": "smoke", "detail": {"origin": "test"}})
    assert created.status_code == 201
    run = created.json()
    assert run["status"] == "created"

    fetched = await client.get(f"/v1/runs/{run['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["detail"] == {"origin": "test"}

    listed = await client.get("/v1/runs", params={"limit": 5})
    assert listed.status_code == 200
    assert any(item["id"] == run["id"] for item in listed.json())


async def test_get_unknown_run_is_404(client: httpx.AsyncClient) -> None:
    missing = await client.get("/v1/runs/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404


async def test_readyz_ready_with_real_db(client: httpx.AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
