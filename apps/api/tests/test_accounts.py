"""S15-1: local accounts, the three product roles, and the first-run gate.

What these tests are actually defending:
 - a fresh deployment is open ONLY until someone claims it, and claiming it needs
   the setup token;
 - authority changes take effect NOW, not when a 12-hour session happens to expire;
 - the role boundary is real — a plain user cannot shape the repository map;
 - the tenant boundary is real — a platform admin acting in another workspace sees
   that workspace and nothing of their own.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from _helpers import make_settings
from asgi_lifespan import LifespanManager
from fastapi import FastAPI

from estimo_api.main import create_app

pytestmark = pytest.mark.db

SETUP_TOKEN = "test-setup-token"
ADMIN = {"email": "admin@estimo.test", "password": "correct-horse-battery", "name": "Admin"}


@pytest.fixture
async def app(database_url: str, clean_tables: None) -> AsyncIterator[FastAPI]:
    settings = make_settings(database_url)
    settings.setup_token = SETUP_TOKEN
    application = create_app(settings)
    async with LifespanManager(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def _bootstrap(client: httpx.AsyncClient) -> str:
    response = await client.post("/v1/auth/bootstrap", json={"setup_token": SETUP_TOKEN, **ADMIN})
    assert response.status_code == 201, response.text
    token: str = response.json()["token"]
    return token


def _auth(token: str, tenant: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if tenant:
        headers["X-Estimo-Tenant"] = tenant
    return headers


async def test_a_fresh_deployment_is_open_until_someone_claims_it(
    client: httpx.AsyncClient,
) -> None:
    # Before bootstrap: no credential needed (the pre-S15 single-tenant behaviour).
    assert (await client.get("/v1/projects")).status_code == 200
    me = (await client.get("/v1/auth/me")).json()
    assert me == {
        "authenticated": False,
        "accounts_exist": False,
        "user": None,
        "tenant": None,
        "role": None,
        "can_sign": False,
    }

    # The setup token is what stops a passer-by from becoming the administrator.
    refused = await client.post("/v1/auth/bootstrap", json={"setup_token": "guessed", **ADMIN})
    assert refused.status_code == 403

    token = await _bootstrap(client)

    # …and the door is shut behind them, for everyone without a token.
    assert (await client.get("/v1/projects")).status_code == 401
    assert (await client.get("/v1/projects", headers=_auth(token))).status_code == 200
    assert (await client.get("/v1/auth/me")).json()["accounts_exist"] is True

    # A second bootstrap cannot mint a second "first" admin.
    again = await client.post("/v1/auth/bootstrap", json={"setup_token": SETUP_TOKEN, **ADMIN})
    assert again.status_code == 409


async def test_login_and_the_password_boundary(client: httpx.AsyncClient) -> None:
    await _bootstrap(client)
    wrong = await client.post(
        "/v1/auth/login", json={"email": ADMIN["email"], "password": "not-it-at-all"}
    )
    assert wrong.status_code == 401
    # An unknown address must be indistinguishable from a wrong password.
    unknown = await client.post(
        "/v1/auth/login", json={"email": "nobody@estimo.test", "password": "not-it-at-all"}
    )
    assert unknown.status_code == 401 and unknown.json() == wrong.json()

    ok = await client.post(
        "/v1/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]}
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["user"]["role"] == "platform_admin" and body["user"]["can_sign"] is True
    # Email is normalized on the way in, so case cannot fork one person into two.
    upper = await client.post(
        "/v1/auth/login", json={"email": ADMIN["email"].upper(), "password": ADMIN["password"]}
    )
    assert upper.status_code == 200


async def test_only_a_platform_admin_manages_accounts(client: httpx.AsyncClient) -> None:
    admin_token = await _bootstrap(client)
    created = await client.post(
        "/v1/users",
        headers=_auth(admin_token),
        json={
            "email": "ayse@estimo.test",
            "name": "Ayşe",
            "password": "another-long-password",
            "role": "user",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["role"] == "user"

    login = await client.post(
        "/v1/auth/login",
        json={"email": "ayse@estimo.test", "password": "another-long-password"},
    )
    user_token = login.json()["token"]

    # A user works the product…
    assert (await client.get("/v1/projects", headers=_auth(user_token))).status_code == 200
    # …but does not administer it, and cannot promote themselves.
    assert (await client.get("/v1/users", headers=_auth(user_token))).status_code == 403
    escalation = await client.patch(
        f"/v1/users/{created.json()['id']}",
        headers=_auth(user_token),
        json={"role": "platform_admin"},
    )
    assert escalation.status_code == 403

    # Duplicate accounts are refused rather than silently shadowing the first.
    duplicate = await client.post(
        "/v1/users",
        headers=_auth(admin_token),
        json={"email": "AYSE@estimo.test", "name": "Ayşe", "password": "yet-another-password"},
    )
    assert duplicate.status_code == 409

    # The deployment cannot be left with nobody able to administer it.
    admins = [u for u in (await client.get("/v1/users", headers=_auth(admin_token))).json()]
    only_admin = next(u for u in admins if u["role"] == "platform_admin")
    lockout = await client.patch(
        f"/v1/users/{only_admin['id']}", headers=_auth(admin_token), json={"is_active": False}
    )
    assert lockout.status_code == 409


async def test_revoking_authority_ends_live_sessions_immediately(
    client: httpx.AsyncClient,
) -> None:
    admin_token = await _bootstrap(client)
    created = await client.post(
        "/v1/users",
        headers=_auth(admin_token),
        json={
            "email": "mehmet@estimo.test",
            "name": "Mehmet",
            "password": "long-enough-password",
            "role": "project_owner",
        },
    )
    user_id = created.json()["id"]
    session = await client.post(
        "/v1/auth/login",
        json={"email": "mehmet@estimo.test", "password": "long-enough-password"},
    )
    owner_token = session.json()["token"]
    assert (
        await client.post(
            "/v1/projects", headers=_auth(owner_token), json={"name": "Core Platform"}
        )
    ).status_code == 201

    # Demote. The token in flight was minted for a project owner and must stop
    # buying project-owner things the moment the role changes — not in 12 hours.
    demoted = await client.patch(
        f"/v1/users/{user_id}", headers=_auth(admin_token), json={"role": "user"}
    )
    assert demoted.status_code == 200
    stale = await client.post(
        "/v1/projects", headers=_auth(owner_token), json={"name": "Second Try"}
    )
    assert stale.status_code == 401, "a demoted session kept its old authority"

    # A fresh session reflects the new role: allowed to read, refused to shape.
    session = await client.post(
        "/v1/auth/login",
        json={"email": "mehmet@estimo.test", "password": "long-enough-password"},
    )
    user_token = session.json()["token"]
    assert (await client.get("/v1/projects", headers=_auth(user_token))).status_code == 200
    refused = await client.post(
        "/v1/projects", headers=_auth(user_token), json={"name": "Second Try"}
    )
    assert refused.status_code == 403

    # Deactivation is the same story, one step harder.
    await client.patch(
        f"/v1/users/{user_id}", headers=_auth(admin_token), json={"is_active": False}
    )
    assert (await client.get("/v1/projects", headers=_auth(user_token))).status_code == 401
    denied = await client.post(
        "/v1/auth/login",
        json={"email": "mehmet@estimo.test", "password": "long-enough-password"},
    )
    assert denied.status_code == 401


async def test_changing_my_own_password_invalidates_my_other_sessions(
    client: httpx.AsyncClient,
) -> None:
    first = await _bootstrap(client)
    second = (
        await client.post(
            "/v1/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]}
        )
    ).json()["token"]

    changed = await client.post(
        "/v1/auth/password",
        headers=_auth(second),
        json={"current_password": ADMIN["password"], "new_password": "a-brand-new-secret"},
    )
    assert changed.status_code == 204
    # The OTHER session — the one on a stolen laptop — is gone too.
    assert (await client.get("/v1/projects", headers=_auth(first))).status_code == 401
    assert (
        await client.post(
            "/v1/auth/login", json={"email": ADMIN["email"], "password": "a-brand-new-secret"}
        )
    ).status_code == 200


async def test_a_workspace_cannot_see_another_workspaces_map(client: httpx.AsyncClient) -> None:
    admin_token = await _bootstrap(client)
    other = await client.post(
        "/v1/tenants", headers=_auth(admin_token), json={"name": "Second Customer"}
    )
    assert other.status_code == 201, other.text
    other_id = other.json()["id"]

    home = await client.post(
        "/v1/projects", headers=_auth(admin_token), json={"name": "Home Project"}
    )
    assert home.status_code == 201
    away = await client.post(
        "/v1/projects",
        headers=_auth(admin_token, tenant=other_id),
        json={"name": "Away Project"},
    )
    assert away.status_code == 201

    # Each workspace sees exactly its own project — the acting-tenant header moves
    # the admin between them rather than merging them.
    home_names = {
        p["name"] for p in (await client.get("/v1/projects", headers=_auth(admin_token))).json()
    }
    away_names = {
        p["name"]
        for p in (
            await client.get("/v1/projects", headers=_auth(admin_token, tenant=other_id))
        ).json()
    }
    assert home_names == {"Home Project"}
    assert away_names == {"Away Project"}

    # And a project owner in the home workspace cannot reach the other one by
    # sending the header themselves.
    await client.post(
        "/v1/users",
        headers=_auth(admin_token),
        json={
            "email": "owner@estimo.test",
            "name": "Owner",
            "password": "owner-password-long",
            "role": "project_owner",
        },
    )
    owner_token = (
        await client.post(
            "/v1/auth/login",
            json={"email": "owner@estimo.test", "password": "owner-password-long"},
        )
    ).json()["token"]
    forged = await client.get("/v1/projects", headers=_auth(owner_token, tenant=other_id))
    assert forged.status_code == 200
    assert {p["name"] for p in forged.json()} == {"Home Project"}, "a header widened a tenant"
