"""S14: importing discovered repositories onto the map through a connection.

What must stay true:
 - an imported repo borrows the configured connection's credential by REFERENCE
   (`derived_from`), never by copy — one credential, one place to rotate it;
 - the borrowed credential can only ever travel to the connection's own host
   (anything else is an exfiltration lever, not a typo);
 - discovery and import are project-owner surfaces — the `user` role reads maps,
   it does not shape them;
 - each imported repo gets its background first sync exactly once.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from _helpers import make_settings
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from estimo_api.main import create_app

pytestmark = pytest.mark.db

BASE = "https://bitbucket.dc.invalid/scm/TTG/ttgomni-bss-backend.git"


@pytest.fixture
async def app(
    database_url: str, clean_tables: None, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[FastAPI]:
    # The import route schedules the same background sync the "Sync now" button
    # uses; a real one would try to clone. Record the calls instead.
    from estimo_api.routers import connections as connections_router

    scheduled: list[uuid.UUID] = []

    async def _record(sessionmaker, connection_id, gateway, tenant) -> None:  # type: ignore[no-untyped-def]
        scheduled.append(connection_id)

    monkeypatch.setattr(connections_router, "_run_sync_bg", _record)
    application = create_app(make_settings(database_url))
    application.state.scheduled_syncs = scheduled
    async with LifespanManager(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def _setup(client: httpx.AsyncClient) -> tuple[str, str]:
    """A project and a configured (sealed-secret) Bitbucket connection."""
    connection = await client.post(
        "/v1/connections",
        json={
            "kind": "bitbucket",
            "name": "ttgomni-bss-backend",
            "base_url": BASE,
            "config": {"auth": "bearer", "username": "svc-estimo"},
            "secret": "dc-pat-value",
        },
    )
    assert connection.status_code == 201, connection.text
    project = await client.post("/v1/projects", json={"name": "TTG Omni"})
    assert project.status_code == 201
    return project.json()["id"], connection.json()["id"]


def _repo(slug: str) -> dict[str, str]:
    return {
        "slug": slug,
        "name": slug,
        "clone_url": f"https://bitbucket.dc.invalid/scm/TTG/{slug}.git",
    }


async def test_import_creates_derived_connections_that_borrow_not_copy(
    client: httpx.AsyncClient, app: FastAPI, database_url: str
) -> None:
    project_id, connection_id = await _setup(client)
    response = await client.post(
        f"/v1/projects/{project_id}/repos/import",
        json={
            "connection_id": connection_id,
            "node_type": "fe",
            "repos": [_repo("ttgomni-fe"), _repo("ttgomni-mobile")],
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["added"], body["connections_created"], body["syncing"]) == (2, 2, 2)
    assert app.state.scheduled_syncs and len(app.state.scheduled_syncs) == 2

    board = (await client.get(f"/v1/projects/{project_id}/map")).json()
    names = {node["name"]: node for node in board["repos"]}
    assert set(names) == {"ttgomni-fe", "ttgomni-mobile"}
    assert names["ttgomni-fe"]["node_type"] == "fe"
    assert names["ttgomni-fe"]["connection"]["kind"] == "bitbucket"

    # The derived rows reference the credential; they do not hold one.
    engine = create_async_engine(database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    from estimo_connectors.db import Connection
    from estimo_connectors.sync import effective_secret

    async with maker() as session:
        derived = (
            (await session.execute(select(Connection).where(Connection.name == "ttgomni-fe")))
            .scalars()
            .one()
        )
        assert derived.secret is None and derived.secret_env is None
        assert derived.config["derived_from"] == connection_id
        assert derived.config["auth"] == "bearer"
        # …and the sync-time resolver follows the reference to the parent's PAT.
        assert await effective_secret(session, derived) == "dc-pat-value"
    await engine.dispose()

    # Re-importing the same repos is a no-op, not an error or a duplicate.
    again = await client.post(
        f"/v1/projects/{project_id}/repos/import",
        json={"connection_id": connection_id, "repos": [_repo("ttgomni-fe")]},
    )
    assert again.status_code == 201
    assert again.json()["added"] == 0 and again.json()["skipped"] == ["ttgomni-fe"]


async def test_a_borrowed_credential_cannot_be_pointed_at_another_host(
    client: httpx.AsyncClient,
) -> None:
    project_id, connection_id = await _setup(client)
    response = await client.post(
        f"/v1/projects/{project_id}/repos/import",
        json={
            "connection_id": connection_id,
            "repos": [
                {
                    "slug": "innocent-looking",
                    "clone_url": "https://attacker.invalid/scm/TTG/innocent-looking.git",
                }
            ],
        },
    )
    assert response.status_code == 422
    assert "must live on the connection's own server" in response.json()["detail"]
    # Nothing was created on the way to the refusal.
    board = (await client.get(f"/v1/projects/{project_id}/map")).json()
    assert board["repos"] == []


async def test_importing_the_connections_own_repo_reuses_it(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    project_id, connection_id = await _setup(client)
    response = await client.post(
        f"/v1/projects/{project_id}/repos/import",
        json={
            "connection_id": connection_id,
            "node_type": "be",
            "repos": [
                {
                    "slug": "ttgomni-bss-backend",
                    "clone_url": BASE,
                }
            ],
        },
    )
    assert response.status_code == 201
    body = response.json()
    # The parent IS this repo: no derived connection, no redundant first sync —
    # the node simply binds to the connection that already exists.
    assert (body["added"], body["connections_created"], body["syncing"]) == (1, 0, 0)
    board = (await client.get(f"/v1/projects/{project_id}/map")).json()
    assert board["repos"][0]["connection_id"] == connection_id


async def test_discovery_and_import_are_owner_surfaces(client: httpx.AsyncClient) -> None:
    """With accounts enabled, the `user` role can read the map but not import."""
    setup_token = "map-import-setup"
    # Recreate the app path via HTTP: bootstrap, then a plain user.
    # (The open-mode fixture client is a platform admin; this test needs a user.)
    from estimo_api.routers import auth as auth_routes  # noqa: F401 — route presence

    boot = await client.post(
        "/v1/auth/bootstrap",
        json={
            "setup_token": setup_token,
            "email": "admin@map.test",
            "name": "Admin",
            "password": "long-enough-password",
            "workspace": "Etiya",
        },
    )
    # The fixture app was built without ESTIMO_SETUP_TOKEN; its boot token is
    # random, so bootstrap must refuse ours — and that refusal is itself the
    # first-run gate working. Use the printed-token lane instead.
    assert boot.status_code == 403

    # Reach the gate the supported way: read the generated token off app state.
    # (An operator reads it off the container log; the test reads it off the app.)
    setup_token = client._transport.app.state.setup_token  # type: ignore[attr-defined]
    boot = await client.post(
        "/v1/auth/bootstrap",
        json={
            "setup_token": setup_token,
            "email": "admin@map.test",
            "name": "Admin",
            "password": "long-enough-password",
            "workspace": "Etiya",
        },
    )
    assert boot.status_code == 201, boot.text
    admin = {"Authorization": f"Bearer {boot.json()['token']}"}

    created = await client.post(
        "/v1/users",
        headers=admin,
        json={
            "email": "user@map.test",
            "name": "Plain User",
            "password": "another-long-password",
            "role": "user",
        },
    )
    assert created.status_code == 201
    login = await client.post(
        "/v1/auth/login", json={"email": "user@map.test", "password": "another-long-password"}
    )
    user = {"Authorization": f"Bearer {login.json()['token']}"}

    connection = await client.post(
        "/v1/connections",
        headers=admin,
        json={
            "kind": "bitbucket",
            "name": "ttg",
            "base_url": BASE,
            "config": {"auth": "bearer"},
            "secret": "pat",
        },
    )
    project = await client.post("/v1/projects", headers=admin, json={"name": "TTG Omni"})

    # The user reads the map…
    assert (
        await client.get(f"/v1/projects/{project.json()['id']}/map", headers=user)
    ).status_code == 200
    # …but may neither browse the credential's reach nor import with it.
    assert (
        await client.get(f"/v1/connections/{connection.json()['id']}/remote-repos", headers=user)
    ).status_code == 403
    assert (
        await client.post(
            f"/v1/projects/{project.json()['id']}/repos/import",
            headers=user,
            json={"connection_id": connection.json()["id"], "repos": [_repo("x")]},
        )
    ).status_code == 403
