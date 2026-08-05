"""S14-1: the repository map as server state.

The map is the product's cornerstone — what the company's repositories are and how
they relate — so these tests pin the properties an estimate built on it depends on:
a relation always has two real ends on the same map, a synced node carries its
connection's live facts, and losing a connection loses the credentials, not the
architecture.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from _helpers import make_settings
from asgi_lifespan import LifespanManager

from estimo_api.main import create_app

pytestmark = pytest.mark.db


@pytest.fixture
async def client(database_url: str, clean_tables: None) -> AsyncIterator[httpx.AsyncClient]:
    # No accounts: the deployment is in its open first-run state, where the
    # synthetic principal is a platform admin. The role boundary itself is proven
    # in test_accounts.py; this file is about the map.
    app = create_app(make_settings(database_url))
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


async def _project(client: httpx.AsyncClient, name: str = "Core Platform") -> str:
    response = await client.post("/v1/projects", json={"name": name})
    assert response.status_code == 201, response.text
    project: str = response.json()["id"]
    return project


async def _repo(client: httpx.AsyncClient, project: str, name: str, **extra: Any) -> str:
    response = await client.post(f"/v1/projects/{project}/repos", json={"name": name, **extra})
    assert response.status_code == 201, response.text
    repo: str = response.json()["id"]
    return repo


async def test_a_project_key_is_derived_and_unique(client: httpx.AsyncClient) -> None:
    first = await client.post("/v1/projects", json={"name": "Core Integration Platform"})
    assert first.json()["key"] == "CIP"
    # Two projects cannot share a key inside one workspace: the key is what people
    # say out loud, so a duplicate is an ambiguity, not a convenience.
    clash = await client.post("/v1/projects", json={"name": "Core Integration Platform"})
    assert clash.status_code == 409
    assert (await client.post("/v1/projects", json={"name": "Loyalty"})).json()["key"] == "L"


async def test_the_map_round_trips_nodes_relations_and_placement(
    client: httpx.AsyncClient,
) -> None:
    project = await _project(client)
    portal = await _repo(client, project, "web-portal-ui", node_type="fe", provider="github")
    gateway = await _repo(client, project, "integration-gateway", node_type="middleware")

    relation = await client.post(
        f"/v1/projects/{project}/relations",
        json={"from_repo_id": portal, "to_repo_id": gateway, "kind": "api"},
    )
    assert relation.status_code == 201 and relation.json()["created"] is True
    # Drawing the same edge again is someone repeating a true statement, not an error.
    again = await client.post(
        f"/v1/projects/{project}/relations",
        json={"from_repo_id": portal, "to_repo_id": gateway, "kind": "api"},
    )
    assert again.status_code == 201 and again.json()["created"] is False
    assert again.json()["id"] == relation.json()["id"]

    moved = await client.patch(
        f"/v1/projects/{project}/repos/{portal}", json={"pos_x": 120.5, "pos_y": 340.0}
    )
    assert moved.status_code == 200

    board = (await client.get(f"/v1/projects/{project}/map")).json()
    assert board["project"]["name"] == "Core Platform"
    nodes = {node["name"]: node for node in board["repos"]}
    assert nodes["web-portal-ui"]["node_type"] == "fe"
    assert (nodes["web-portal-ui"]["pos_x"], nodes["web-portal-ui"]["pos_y"]) == (120.5, 340.0)
    assert nodes["integration-gateway"]["pos_x"] is None, "an undragged node stays auto-laid-out"
    assert len(board["relations"]) == 1

    # Auto-layout is the absence of a stored point, not a second kind of point.
    reset = await client.patch(
        f"/v1/projects/{project}/repos/{portal}", json={"reset_position": True}
    )
    assert reset.status_code == 200
    board = (await client.get(f"/v1/projects/{project}/map")).json()
    assert next(n for n in board["repos"] if n["id"] == portal)["pos_x"] is None

    # Deleting a node takes its relations with it — an edge to nothing is not a
    # relation, it is a dangling reference someone would later read as fact.
    assert (await client.delete(f"/v1/projects/{project}/repos/{portal}")).status_code == 204
    board = (await client.get(f"/v1/projects/{project}/map")).json()
    assert board["relations"] == [] and len(board["repos"]) == 1


async def test_a_relation_needs_two_real_ends_on_the_same_map(
    client: httpx.AsyncClient,
) -> None:
    project = await _project(client)
    other = await _project(client, "Loyalty Program")
    here = await _repo(client, project, "payments-service")
    elsewhere = await _repo(client, other, "loyalty-api")

    lonely = await client.post(
        f"/v1/projects/{project}/relations",
        json={"from_repo_id": here, "to_repo_id": here, "kind": "api"},
    )
    assert lonely.status_code == 422, "a repository cannot consume itself"

    crossing = await client.post(
        f"/v1/projects/{project}/relations",
        json={"from_repo_id": here, "to_repo_id": elsewhere, "kind": "api"},
    )
    assert crossing.status_code == 404, "an edge across projects is invisible from both sides"

    ghost = await client.post(
        f"/v1/projects/{project}/relations",
        json={"from_repo_id": here, "to_repo_id": str(uuid.uuid4()), "kind": "data"},
    )
    assert ghost.status_code == 404


async def test_a_synced_node_carries_its_connections_facts_and_survives_it(
    client: httpx.AsyncClient,
) -> None:
    created = await client.post(
        "/v1/connections",
        json={
            "kind": "bitbucket",
            "name": "ttgomni-bss-backend",
            "base_url": "https://bitbucket.invalid/scm/TTG/backend.git",
            "config": {"auth": "bearer"},
            "secret": "not-a-real-token",
        },
    )
    assert created.status_code == 201, created.text
    connection_id = created.json()["id"]

    project = await _project(client)
    node = await _repo(
        client,
        project,
        "ttgomni-bss-backend",
        node_type="be",
        provider="bitbucket",
        connection_id=connection_id,
    )
    board = (await client.get(f"/v1/projects/{project}/map")).json()
    linked = next(n for n in board["repos"] if n["id"] == node)
    assert linked["connection"]["kind"] == "bitbucket"
    assert linked["connection"]["name"] == "ttgomni-bss-backend"

    # Deleting the connection deletes the credentials and the index — never the
    # architecture drawn around it. The node degrades to a declared repository.
    assert (await client.delete(f"/v1/connections/{connection_id}")).status_code == 204
    board = (await client.get(f"/v1/projects/{project}/map")).json()
    survivor = next(n for n in board["repos"] if n["id"] == node)
    assert survivor["connection_id"] is None and survivor["connection"] is None
    assert survivor["name"] == "ttgomni-bss-backend"

    unknown = await client.post(
        f"/v1/projects/{project}/repos",
        json={"name": "phantom", "connection_id": str(uuid.uuid4())},
    )
    assert unknown.status_code == 404


async def test_deleting_a_project_takes_its_whole_map(client: httpx.AsyncClient) -> None:
    project = await _project(client)
    first = await _repo(client, project, "a-service")
    second = await _repo(client, project, "b-service")
    await client.post(
        f"/v1/projects/{project}/relations",
        json={"from_repo_id": first, "to_repo_id": second, "kind": "data"},
    )
    assert (await client.delete(f"/v1/projects/{project}")).status_code == 204
    assert (await client.get(f"/v1/projects/{project}/map")).status_code == 404
    assert (await client.get("/v1/projects")).json() == []
