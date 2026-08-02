"""Gateway behavior against a respx-mocked OpenAI-compatible endpoint."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import respx
from pydantic import SecretStr

from estimo_gateway import (
    GatewayClient,
    GatewayConfig,
    GatewayRateLimitedError,
    GatewayStatusError,
    UnknownStageError,
)
from estimo_gateway.client import redact_headers

BASE_URL = "http://gateway.local/v1"


def make_config(**overrides: Any) -> GatewayConfig:
    base: dict[str, Any] = {
        "base_url": BASE_URL,
        "api_key": SecretStr("sk-test-virtual-key"),
        "max_retries": 2,
        "profiles": {"default": "balanced", "reading": "precise-long"},
    }
    base.update(overrides)
    return GatewayConfig.model_validate(base)


def completion_body(text: str = "ok", model: str = "balanced") -> dict[str, Any]:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1_700_000_000,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9},
    }


@pytest.fixture
async def client() -> AsyncIterator[GatewayClient]:
    gateway = GatewayClient(make_config())
    yield gateway
    await gateway.aclose()


@respx.mock
async def test_complete_routes_stage_to_profile(client: GatewayClient) -> None:
    route = respx.post(f"{BASE_URL}/chat/completions").respond(
        200, json=completion_body(model="precise-long")
    )
    result = await client.complete("reading", [{"role": "user", "content": "merhaba"}])
    assert result.text == "ok"
    assert result.prompt_tokens == 7
    sent = route.calls.last.request
    assert b'"model":"precise-long"' in sent.content.replace(b" ", b"")


@respx.mock
async def test_unknown_stage_without_default_raises() -> None:
    gateway = GatewayClient(make_config(profiles={"reading": "precise-long"}))
    try:
        with pytest.raises(UnknownStageError):
            await gateway.complete("smoke", [{"role": "user", "content": "x"}])
    finally:
        await gateway.aclose()


@respx.mock
async def test_429_retried_then_succeeds(client: GatewayClient) -> None:
    """Transport retries live in the openai client and honor Retry-After."""
    route = respx.post(f"{BASE_URL}/chat/completions")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0"}, json={"error": {"message": "rl"}}),
        httpx.Response(200, json=completion_body()),
    ]
    result = await client.complete("reading", [{"role": "user", "content": "x"}])
    assert result.text == "ok"
    assert route.call_count == 2


@respx.mock
async def test_429_exhausted_surfaces_typed_error() -> None:
    gateway = GatewayClient(make_config(max_retries=1))
    respx.post(f"{BASE_URL}/chat/completions").respond(
        429, headers={"Retry-After": "0"}, json={"error": {"message": "budget exceeded"}}
    )
    try:
        with pytest.raises(GatewayRateLimitedError):
            await gateway.complete("reading", [{"role": "user", "content": "x"}])
    finally:
        await gateway.aclose()


@respx.mock
async def test_5xx_surfaces_status_error() -> None:
    gateway = GatewayClient(make_config(max_retries=0))
    respx.post(f"{BASE_URL}/chat/completions").respond(500, json={"error": {"message": "boom"}})
    try:
        with pytest.raises(GatewayStatusError) as excinfo:
            await gateway.complete("reading", [{"role": "user", "content": "x"}])
        assert excinfo.value.status_code == 500
    finally:
        await gateway.aclose()


@respx.mock
async def test_embed_returns_dimension(client: GatewayClient) -> None:
    respx.post(f"{BASE_URL}/embeddings").respond(
        200,
        json={
            "object": "list",
            "model": "embed-small",
            "data": [
                {"object": "embedding", "index": 0, "embedding": [0.1, 0.2, 0.3, 0.4]},
                {"object": "embedding", "index": 1, "embedding": [0.4, 0.3, 0.2, 0.1]},
            ],
            "usage": {"prompt_tokens": 5, "total_tokens": 5},
        },
    )
    result = await client.embed(["a", "b"], stage="reading")
    assert result.dimension == 4
    assert len(result.vectors) == 2


@respx.mock
async def test_logs_metadata_without_credentials(
    client: GatewayClient, caplog: pytest.LogCaptureFixture
) -> None:
    respx.post(f"{BASE_URL}/chat/completions").respond(
        200, json=completion_body(), headers={"x-request-id": "req-42"}
    )
    with caplog.at_level("INFO", logger="estimo.gateway"):
        await client.complete("reading", [{"role": "user", "content": "gizli içerik"}])
    joined = " ".join(record.getMessage() for record in caplog.records)
    assert "req-42" in joined
    assert "sk-test-virtual-key" not in joined
    assert "gizli içerik" not in joined


def test_redact_headers_strips_credentials() -> None:
    headers = httpx.Headers({"Authorization": "Bearer sk-x", "X-Request-Id": "1"})
    redacted = redact_headers(headers)
    assert "authorization" not in {k.lower() for k in redacted}
    assert redacted.get("x-request-id") == "1"
