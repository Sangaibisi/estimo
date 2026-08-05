"""Admin → System: the runtime config surface must inform without leaking.

The whole point of `GET /v1/system` is to answer "what is this deployment actually
configured to do?" from inside the product — and the whole risk is that a config
readout becomes a credential oracle. These tests pin both directions, and they pin
the SHAPE of the responses (an exact key whitelist), because a blacklist of known
secret substrings cannot veto a field nobody thought about.

Role gating for this surface lives in test_auth.py (`test_system_surface_is_admin_only`)
— these tests run in open mode, where every caller holds every role by design.
"""

from collections.abc import AsyncIterator

import httpx
import pytest
import respx
from _helpers import make_settings
from asgi_lifespan import LifespanManager
from pydantic import SecretStr

from estimo_api.main import create_app
from estimo_gateway import GatewayConfig

pytestmark = pytest.mark.db


def _gateway_key(database_url: str) -> str:
    """Derived from the same Settings the fixture builds — a hardcoded copy could
    drift and quietly turn every "key is absent" assertion vacuous."""
    gateway = make_settings(database_url).gateway
    assert gateway is not None, "the shared test settings are supposed to carry one"
    return gateway.api_key.get_secret_value()


def _keys(obj: object, prefix: str = "") -> set[str]:
    """Flatten a JSON object to dotted key paths, so tests can whitelist the shape."""
    if not isinstance(obj, dict):
        return set()
    out: set[str] = set()
    for key, value in obj.items():
        path = f"{prefix}{key}"
        out.add(path)
        out |= _keys(value, f"{path}.")
    return out


SYSTEM_SHAPE = {
    "version",
    "auth",
    "auth.mode",
    "auth.issuer",
    "auth.audience",
    "auth.role_claim",
    "auth.tenant_claim",
    "auth.acl_claim",
    "gateway",
    # False = neither the panel nor the environment holds one; the API still boots
    # (ADR-0008/0009 — the gateway is panel-managed) and the panel says so.
    "gateway.configured",
    # Is there an env gateway underneath a panel override — decides whether dropping
    # the override reverts to something or removes the gateway entirely.
    "gateway.env_present",
    "gateway.base_url",
    "gateway.api_key_present",
    "gateway.profiles",
    "gateway.timeout_seconds",
    "gateway.connect_timeout_seconds",
    "gateway.max_retries",
    # ADR-0008: where the effective config came from, whether stored secrets are
    # encrypted (False = plain:-prefixed rows; the panel warns), and whether a
    # stored key still unseals (False = running on the env key after a rotation).
    "gateway.source",
    "gateway.secrets_encrypted",
    "gateway.stored_key_readable",
    "database",
    "database.host",
    "database.name",
    "database.role",
    "cors_origins",
}


@pytest.fixture
async def client(database_url: str, clean_tables: None) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(make_settings(database_url))
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


async def test_system_reports_config_without_secrets(
    client: httpx.AsyncClient, database_url: str
) -> None:
    response = await client.get("/v1/system")
    assert response.status_code == 200, response.text
    body = response.json()

    # Informative half: the operator can see where model calls go and how stages route.
    assert body["gateway"]["base_url"].startswith("http://mock-llm.invalid")
    assert body["gateway"]["profiles"] == {"default": "mock-small"}
    assert body["gateway"]["api_key_present"] is True
    assert body["auth"]["mode"] == "open"
    dsn = httpx.URL(database_url.replace("+asyncpg", ""))
    assert body["database"]["name"] == dsn.path.lstrip("/")
    assert body["database"]["host"] == dsn.host
    assert body["version"]

    # Redaction half. First the shape: EXACTLY the whitelisted keys, so a future
    # field cannot ship unreviewed. (`gateway.profiles.*` values are profile names.)
    assert _keys(body) - {f"gateway.profiles.{k}" for k in body["gateway"]["profiles"]} == (
        SYSTEM_SHAPE
    )
    # Then the known credential material.
    assert _gateway_key(database_url) not in response.text
    assert "password" not in response.text.lower()


async def test_system_database_block_never_carries_the_dsn_password(
    client: httpx.AsyncClient, database_url: str
) -> None:
    """The realistic leak is the DSN itself (str(PostgresDsn) prints the password).

    A bare-substring check on the password would be stricter but is unusable here:
    CI's DSN uses the same word for role, database, and password, so the password
    "appears" in perfectly legitimate fields. The `:password@` authority form is the
    shape an actual leak takes; the key-whitelist test above closes the rest.
    """
    password = httpx.URL(database_url.replace("+asyncpg", "")).password
    assert password, "test DSN unexpectedly has no password — the assertion below is void"
    response = await client.get("/v1/system")
    assert f":{password}@" not in response.text
    assert "postgresql" not in response.text, "a raw DSN reached the response"


async def test_a_userinfo_password_in_the_gateway_url_is_stripped(
    database_url: str, clean_tables: None
) -> None:
    """Operators front gateways with basic-auth proxies and put the credential in
    the URL. `str(HttpUrl)` preserves userinfo, so serializing the raw config value
    would print the proxy password on every admin page load."""
    settings = make_settings(database_url)
    settings.gateway = GatewayConfig(
        base_url="https://estimo:S3cretProxyPass@llm.corp.invalid:8443/v1",
        api_key=SecretStr("sk-test"),
        profiles={"default": "mock-small"},
    )
    app = create_app(settings)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            response = await http.get("/v1/system")
    assert response.status_code == 200
    assert "S3cretProxyPass" not in response.text
    assert "estimo:" not in response.json()["gateway"]["base_url"]
    # Host, port and path survive — the operator still learns where calls go.
    assert response.json()["gateway"]["base_url"] == "https://llm.corp.invalid:8443/v1"


@respx.mock
async def test_gateway_check_round_trips_and_times(
    client: httpx.AsyncClient, database_url: str
) -> None:
    respx.post("http://mock-llm.invalid/v1/chat/completions").respond(
        200,
        json={
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "created": 0,
            "model": "mock-small",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9},
        },
    )
    response = await client.post("/v1/system/gateway-check")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["model"] == "mock-small"
    assert isinstance(body["latency_ms"], int)
    assert set(body) == {"ok", "model", "latency_ms"}
    assert _gateway_key(database_url) not in response.text


@respx.mock
async def test_gateway_check_never_relays_an_upstream_error_body(
    client: httpx.AsyncClient, database_url: str
) -> None:
    """The classic trap: a proxy answers 401 and helpfully echoes the API key it
    was shown ("Received API Key = sk-…"). The OpenAI client embeds that WHOLE body
    in the exception message, so `str(exc)` would hand the credential to the admin
    page. The endpoint must report our words, never the upstream's."""
    key = _gateway_key(database_url)
    respx.post("http://mock-llm.invalid/v1/chat/completions").respond(
        401,
        json={
            "error": {
                "message": f"Authentication Error, Received API Key = {key}, "
                "Key Hash (Token) = deadbeef",
                "type": "auth_error",
            }
        },
    )
    response = await client.post("/v1/system/gateway-check")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert key not in response.text, "the upstream error body reached the response"
    assert "401" in body["error"], "the operator still learns the status class"
    assert set(body) == {"ok", "latency_ms", "error"}


async def test_gateway_check_reports_an_unreachable_gateway_as_a_finding(
    client: httpx.AsyncClient, database_url: str
) -> None:
    """`.invalid` never resolves (RFC 2606), so this exercises the real failure path:
    still HTTP 200, ok=false, and a reason the admin screen can print."""
    response = await client.post("/v1/system/gateway-check")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"]
    assert _gateway_key(database_url) not in response.text


@pytest.fixture
async def bare_client(database_url: str, clean_tables: None) -> AsyncIterator[httpx.AsyncClient]:
    """A deployment with NO gateway in the environment — the fresh-install shape."""
    from estimo_api.settings import Settings

    settings = Settings(database_url=database_url)
    assert settings.gateway is None, "the environment must not be required to hold one"
    app = create_app(settings)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


async def test_the_api_boots_with_no_gateway_anywhere(bare_client: httpx.AsyncClient) -> None:
    """ADR-0008/0009: the gateway is panel-managed, so a fresh deployment must not
    need an API key in a file to START. Requiring it meant the one setting most
    likely to be wrong at install time could stop the process that owns the screen
    for fixing it."""
    response = await bare_client.get("/v1/system")
    assert response.status_code == 200, response.text
    gateway = response.json()["gateway"]
    assert gateway["configured"] is False
    assert gateway["api_key_present"] is False
    assert gateway["base_url"] is None
    # "unset" is its own answer: naming "environment" would send an operator to look
    # in a file that holds nothing.
    assert gateway["source"] == "unset"


async def test_the_gateway_check_says_there_is_no_gateway_rather_than_500ing(
    bare_client: httpx.AsyncClient,
) -> None:
    response = await bare_client.post("/v1/system/gateway-check")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is False
    assert "no model gateway is configured" in body["error"]


async def test_the_panel_alone_is_a_complete_configuration(
    bare_client: httpx.AsyncClient,
) -> None:
    """The whole point of ADR-0008: an operator with an empty .env can stand the
    product up and give it a model from the Admin screen."""
    saved = await bare_client.put(
        "/v1/system/gateway",
        json={
            "base_url": "http://panel-only.invalid/v1",
            "api_key": "sk-from-the-panel",
            "profiles": {"default": "panel-model"},
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["configured"] is True

    gateway = (await bare_client.get("/v1/system")).json()["gateway"]
    assert gateway["configured"] is True
    assert gateway["source"] == "panel"
    assert gateway["base_url"] == "http://panel-only.invalid/v1"
    assert gateway["api_key_present"] is True
    assert gateway["profiles"] == {"default": "panel-model"}
    # The key never comes back out, panel-set or not.
    assert "sk-from-the-panel" not in (await bare_client.get("/v1/system")).text


async def test_a_half_configured_gateway_is_reported_as_unconfigured(
    bare_client: httpx.AsyncClient,
) -> None:
    """An endpoint with no credential is not a gateway that half-works — it is one
    that cannot work, and saying so is what lets every consumer take its documented
    degraded path instead of building a client that will fail on first use."""
    saved = await bare_client.put(
        "/v1/system/gateway", json={"base_url": "http://panel-only.invalid/v1"}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["configured"] is False


async def test_a_second_save_does_not_delete_the_endpoint(
    bare_client: httpx.AsyncClient,
) -> None:
    """The panel omits an unchanged base_url on purpose — the value in that field came
    from /v1/system with userinfo STRIPPED, so echoing it back would persist a redacted
    URL over a working one. The handler used to rebuild the stored document from the
    body, so the second save — change a timeout, change a profile — deleted the
    gateway. This is the shape of every save after the first."""
    first = await bare_client.put(
        "/v1/system/gateway",
        json={
            "base_url": "http://panel-only.invalid/v1",
            "api_key": "sk-1",
            "profiles": {"default": "m"},
        },
    )
    assert first.json()["configured"] is True

    # A realistic second save: only the timeout changed.
    second = await bare_client.put("/v1/system/gateway", json={"timeout_seconds": 42})
    assert second.status_code == 200, second.text
    assert second.json()["configured"] is True, "the second save dropped the endpoint"
    assert second.json()["base_url"] == "http://panel-only.invalid/v1"
    assert second.json()["timeout_seconds"] == 42
    assert second.json()["api_key_present"] is True


async def test_an_invalid_endpoint_is_refused_even_without_a_key(
    bare_client: httpx.AsyncClient,
) -> None:
    """The endpoint check used to ride on constructing a full config, which is skipped
    when there is no credential — so a typo was persisted with HTTP 200 and surfaced
    later as a 500 from an unrelated request."""
    response = await bare_client.put("/v1/system/gateway", json={"base_url": "not-a-url-at-all"})
    assert response.status_code == 422, response.text
    assert (await bare_client.get("/v1/system")).json()["gateway"]["source"] == "unset"
