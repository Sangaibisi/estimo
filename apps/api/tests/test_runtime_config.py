"""ADR-0008: panel-managed runtime settings — precedence, sealing, immediacy.

The properties that matter:
- panel (DB) beats environment, per FIELD;
- a saved api_key rests SEALED in the row, never plaintext when a master key is set;
- a saved key is never serialized back out, but survives edits that omit it;
- gateway-check exercises the EFFECTIVE config, so "save then test" is truthful;
- reset returns cleanly to the environment.
"""

from collections.abc import AsyncIterator

import httpx
import pytest
import respx
from _helpers import make_settings
from asgi_lifespan import LifespanManager
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from estimo_api.main import create_app
from estimo_core import secrets as core_secrets

pytestmark = pytest.mark.db


@pytest.fixture
async def client(database_url: str, clean_tables: None) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(make_settings(database_url))
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


@pytest.fixture(autouse=True)
async def _clean_runtime_settings(database_url: str) -> AsyncIterator[None]:
    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM runtime_settings"))
    yield
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM runtime_settings"))
    await engine.dispose()


async def test_panel_override_beats_environment_per_field(client: httpx.AsyncClient) -> None:
    saved = await client.put(
        "/v1/system/gateway",
        json={"base_url": "http://litellm.corp.invalid/v1"},
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["base_url"] == "http://litellm.corp.invalid/v1"
    assert body["source"] == "panel"
    # Fields the operator did NOT set keep their env defaults.
    assert body["profiles"] == {"default": "mock-small"}
    assert body["api_key_present"] is True

    listed = await client.get("/v1/system")
    assert listed.json()["gateway"]["base_url"] == "http://litellm.corp.invalid/v1"
    assert listed.json()["gateway"]["source"] == "panel"


async def test_saved_api_key_is_sealed_at_rest_and_never_serialized(
    client: httpx.AsyncClient,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(core_secrets.MASTER_KEY_ENV, "unit-test-master-key")
    response = await client.put("/v1/system/gateway", json={"api_key": "sk-corp-REAL-KEY-123"})
    assert response.status_code == 200
    assert "sk-corp-REAL-KEY-123" not in response.text

    engine = create_async_engine(database_url)
    async with async_sessionmaker(engine)() as session:
        row = (
            await session.execute(text("SELECT value FROM runtime_settings WHERE key='gateway'"))
        ).scalar_one()
    await engine.dispose()
    stored = row["api_key"]
    assert stored.startswith("enc:"), "master key was set — the row must be encrypted"
    assert "sk-corp-REAL-KEY-123" not in stored
    assert core_secrets.unseal(stored) == "sk-corp-REAL-KEY-123"

    # An edit that omits api_key keeps the stored one (write-only semantics).
    edited = await client.put("/v1/system/gateway", json={"base_url": "http://other.invalid/v1"})
    assert edited.json()["api_key_present"] is True
    listed = await client.get("/v1/system")
    assert "sk-corp-REAL-KEY-123" not in listed.text


async def test_without_master_key_the_row_is_visibly_plain(
    client: httpx.AsyncClient,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No silent pseudo-security: without ESTIMO_SECRET_KEY the stored value wears
    a legible plain: prefix and /v1/system says secrets_encrypted=false."""
    monkeypatch.delenv(core_secrets.MASTER_KEY_ENV, raising=False)
    await client.put("/v1/system/gateway", json={"api_key": "sk-plain-key"})

    engine = create_async_engine(database_url)
    async with async_sessionmaker(engine)() as session:
        row = (
            await session.execute(text("SELECT value FROM runtime_settings WHERE key='gateway'"))
        ).scalar_one()
    await engine.dispose()
    assert row["api_key"] == "plain:sk-plain-key"

    info = await client.get("/v1/system")
    assert info.json()["gateway"]["secrets_encrypted"] is False


@respx.mock
async def test_gateway_check_uses_the_panel_override(client: httpx.AsyncClient) -> None:
    """Save-then-test must test what was saved, not the env value."""
    route = respx.post("http://panel-target.invalid/v1/chat/completions").respond(
        200,
        json={
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "created": 0,
            "model": "corp-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )
    await client.put(
        "/v1/system/gateway",
        json={"base_url": "http://panel-target.invalid/v1", "profiles": {"default": "corp-model"}},
    )
    checked = await client.post("/v1/system/gateway-check")
    assert checked.json()["ok"] is True, checked.text
    assert checked.json()["model"] == "corp-model"
    assert route.called


async def test_a_broken_url_is_refused_not_saved(client: httpx.AsyncClient) -> None:
    response = await client.put("/v1/system/gateway", json={"base_url": "not a url"})
    assert response.status_code == 422
    # And nothing was persisted: the readout still reports the environment.
    assert (await client.get("/v1/system")).json()["gateway"]["source"] == "environment"


async def test_validation_errors_never_echo_the_submitted_secret(
    client: httpx.AsyncClient,
) -> None:
    """FastAPI's default 422 includes each failing field's INPUT. Since ADR-0008 lets
    operators paste credentials INTO the API, that default reflects the credential to
    the caller — and through the web client's error banner, into the DOM. Every
    validated body on the app is covered by the handler in main.py, so this pins the
    behaviour on all three shapes that carry a secret."""
    over_long = "sk-LEAKY-" + "x" * 500
    response = await client.put("/v1/system/gateway", json={"api_key": over_long})
    assert response.status_code == 422
    assert "sk-LEAKY-" not in response.text

    # A userinfo-bearing URL failing validation alongside.
    response = await client.put(
        "/v1/system/gateway",
        json={"base_url": "https://user:S3cret@" + "h" * 500, "api_key": over_long},
    )
    assert response.status_code == 422
    assert "S3cret" not in response.text and "sk-LEAKY-" not in response.text

    # A non-OBJECT body: the value itself is the secret.
    response = await client.put("/v1/system/gateway", json="sk-BARE-KEY")
    assert response.status_code == 422
    assert "sk-BARE-KEY" not in response.text

    # And the connection lane, whose credential field is the largest of all.
    response = await client.post(
        "/v1/connections",
        json={
            "kind": "git",
            "name": "leaky",
            "base_url": "https://x.invalid",
            "config": {},
            "secret": "glpat-LEAKY-" + "x" * 4000,
        },
    )
    assert response.status_code == 422
    assert "glpat-LEAKY-" not in response.text


async def test_a_key_that_will_not_unseal_degrades_instead_of_500ing(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rotating ESTIMO_SECRET_KEY is a legitimate ops action the sealing module
    anticipates. If reading the stored key raised, every consumer would 500 at once —
    including GET /v1/system, which renders the Admin panel holding the re-entry field
    and the revert button the error message points at. The recovery route must survive
    the failure it recovers from."""
    monkeypatch.setenv(core_secrets.MASTER_KEY_ENV, "key-one")
    await client.put("/v1/system/gateway", json={"api_key": "sk-sealed-under-key-one"})

    monkeypatch.setenv(core_secrets.MASTER_KEY_ENV, "key-two")
    info = await client.get("/v1/system")
    assert info.status_code == 200, "the recovery panel's own endpoint went down"
    gateway = info.json()["gateway"]
    assert gateway["stored_key_readable"] is False, "the degradation must be visible"
    assert gateway["api_key_present"] is True, "it fell back to the environment key"

    # gateway-check keeps its always-200 contract rather than raising.
    checked = await client.post("/v1/system/gateway-check")
    assert checked.status_code == 200

    # And the documented recovery works.
    reset = await client.put("/v1/system/gateway", json={"reset": True})
    assert reset.status_code == 200 and reset.json()["source"] == "environment"


async def test_removing_every_profile_row_takes_effect(client: httpx.AsyncClient) -> None:
    """`profiles or env.profiles` would resurrect the environment's routing the moment
    an operator deliberately cleared it — leaving the panel showing empty while calls
    still resolved against the old profiles."""
    saved = await client.put("/v1/system/gateway", json={"profiles": {}})
    assert saved.status_code == 200
    assert saved.json()["profiles"] == {}
    assert (await client.get("/v1/system")).json()["gateway"]["profiles"] == {}


async def test_clear_api_key_falls_back_to_the_environment_key(
    client: httpx.AsyncClient, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(core_secrets.MASTER_KEY_ENV, "unit-test-master-key")
    await client.put("/v1/system/gateway", json={"api_key": "sk-stored"})
    cleared = await client.put(
        "/v1/system/gateway", json={"clear_api_key": True, "base_url": "http://x.invalid/v1"}
    )
    assert cleared.status_code == 200
    assert cleared.json()["api_key_present"] is True  # the env key is still there

    engine = create_async_engine(database_url)
    async with async_sessionmaker(engine)() as session:
        row = (
            await session.execute(text("SELECT value FROM runtime_settings WHERE key='gateway'"))
        ).scalar_one()
    await engine.dispose()
    assert "api_key" not in row, "the stored key survived clear_api_key"


async def test_reset_returns_to_the_environment(client: httpx.AsyncClient) -> None:
    await client.put("/v1/system/gateway", json={"base_url": "http://x.invalid/v1"})
    reset = await client.put("/v1/system/gateway", json={"reset": True})
    assert reset.json()["source"] == "environment"
    assert reset.json()["base_url"].startswith("http://mock-llm.invalid")
    assert (await client.get("/v1/system")).json()["gateway"]["source"] == "environment"


async def test_connection_stored_secret_is_sealed_and_not_serialized(
    client: httpx.AsyncClient, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(core_secrets.MASTER_KEY_ENV, "unit-test-master-key")
    created = await client.post(
        "/v1/connections",
        json={
            "kind": "git",
            "name": "panel-secret-conn",
            "base_url": "https://git.corp.invalid/repo.git",
            "config": {},
            "secret": "glpat-SUPER-SECRET-TOKEN",
        },
    )
    assert created.status_code == 201, created.text
    assert "glpat-SUPER-SECRET-TOKEN" not in created.text
    assert created.json()["secret_stored"] is True
    assert created.json()["secret_present"] is True

    listed = await client.get("/v1/connections")
    assert "glpat-SUPER-SECRET-TOKEN" not in listed.text

    engine = create_async_engine(database_url)
    async with async_sessionmaker(engine)() as session:
        stored = (
            await session.execute(
                text("SELECT secret FROM connections WHERE name='panel-secret-conn'")
            )
        ).scalar_one()
    await engine.dispose()
    assert stored.startswith("enc:")
    assert core_secrets.unseal(stored) == "glpat-SUPER-SECRET-TOKEN"


def test_seal_roundtrip_and_key_rotation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(core_secrets.MASTER_KEY_ENV, "key-one")
    sealed = core_secrets.seal("value")
    assert core_secrets.is_encrypted(sealed)
    assert core_secrets.unseal(sealed) == "value"

    monkeypatch.setenv(core_secrets.MASTER_KEY_ENV, "key-two")
    with pytest.raises(core_secrets.SealedSecretError, match="rotated"):
        core_secrets.unseal(sealed)

    monkeypatch.delenv(core_secrets.MASTER_KEY_ENV)
    with pytest.raises(core_secrets.SealedSecretError, match="is not set"):
        core_secrets.unseal(sealed)
    assert core_secrets.unseal(core_secrets.seal("v2")) == "v2"
