"""OpenAI-compatible gateway client.

Layering contract (verified against the founding research §5.4 and current SDK
internals): transport-level retries (connection errors / 408 / 429 / 5xx, Retry-After
aware, full-jitter backoff) belong to the openai client's built-in `max_retries`;
step-level retries belong to the pipeline layer — never add a third retry wrapper
around these calls, or retry counts multiply.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
import openai
from openai import AsyncOpenAI

from estimo_gateway.config import GatewayConfig

logger = logging.getLogger("estimo.gateway")

_REDACTED_HEADERS = {"authorization", "api-key", "x-api-key", "cookie"}
_REQUEST_ID_HEADERS = ("x-request-id", "x-litellm-call-id")


class GatewayError(Exception):
    """Base class for gateway failures surfaced to callers."""


class UnknownStageError(GatewayError):
    def __init__(self, stage: str) -> None:
        super().__init__(
            f"no model profile configured for stage {stage!r} and no 'default' profile exists"
        )
        self.stage = stage


class GatewayRateLimitedError(GatewayError):
    """429 after client-side retries were exhausted (rate limit or budget cap)."""


class GatewayConnectionError(GatewayError):
    """The gateway could not be reached."""


class GatewayStatusError(GatewayError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"gateway returned {status_code}: {message}")
        self.status_code = status_code


@dataclass(frozen=True)
class CompletionResult:
    text: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    request_id: str | None


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    model: str
    dimension: int
    prompt_tokens: int | None


async def _on_request(request: httpx.Request) -> None:
    request.extensions["estimo_start"] = time.monotonic()


async def _on_response(response: httpx.Response) -> None:
    # Metadata only; the body is deliberately never read here (streams would break and
    # prompt content must not reach logs — content capture is an explicit opt-in at the
    # call site, mirroring the OTel GenAI conventions).
    started = response.request.extensions.get("estimo_start")
    elapsed_ms = round((time.monotonic() - started) * 1000) if started else None
    request_id = next(
        (response.headers[h] for h in _REQUEST_ID_HEADERS if h in response.headers), None
    )
    logger.info(
        "gateway call method=%s path=%s status=%s elapsed_ms=%s request_id=%s",
        response.request.method,
        response.request.url.path,
        response.status_code,
        elapsed_ms,
        request_id,
    )


def _build_http_client(config: GatewayConfig) -> httpx.AsyncClient:
    # A custom http_client replaces the SDK defaults entirely, so timeouts and limits
    # must be set explicitly here.
    return httpx.AsyncClient(
        timeout=httpx.Timeout(config.timeout_seconds, connect=config.connect_timeout_seconds),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        event_hooks={"request": [_on_request], "response": [_on_response]},
    )


def redact_headers(headers: httpx.Headers) -> dict[str, str]:
    """Debug helper: headers with credentials removed. Never log raw headers."""
    return {k: v for k, v in headers.items() if k.lower() not in _REDACTED_HEADERS}


class GatewayClient:
    """Async client for chat completions and embeddings through the gateway."""

    def __init__(self, config: GatewayConfig) -> None:
        self._config = config
        self._http_client = _build_http_client(config)
        self._client = AsyncOpenAI(
            base_url=str(config.base_url),
            api_key=config.api_key.get_secret_value(),
            max_retries=config.max_retries,
            http_client=self._http_client,
        )

    def _resolve_model(self, stage: str) -> str:
        model = self._config.model_for_stage(stage)
        if model is None:
            raise UnknownStageError(stage)
        return model

    async def complete(
        self,
        stage: str,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> CompletionResult:
        model = self._resolve_model(stage)
        try:
            response = await self._client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except openai.APIConnectionError as exc:
            raise GatewayConnectionError(str(exc)) from exc
        except openai.RateLimitError as exc:
            raise GatewayRateLimitedError(str(exc)) from exc
        except openai.APIStatusError as exc:
            raise GatewayStatusError(exc.status_code, exc.message) from exc
        usage = response.usage
        return CompletionResult(
            text=response.choices[0].message.content or "",
            model=response.model,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
            request_id=getattr(response, "_request_id", None),
        )

    async def embed(self, texts: list[str], *, stage: str = "embedding") -> EmbeddingResult:
        model = self._resolve_model(stage)
        try:
            response = await self._client.embeddings.create(model=model, input=texts)
        except openai.APIConnectionError as exc:
            raise GatewayConnectionError(str(exc)) from exc
        except openai.RateLimitError as exc:
            raise GatewayRateLimitedError(str(exc)) from exc
        except openai.APIStatusError as exc:
            raise GatewayStatusError(exc.status_code, exc.message) from exc
        vectors = [item.embedding for item in response.data]
        if not vectors or not vectors[0]:
            msg = "gateway returned no embedding vectors"
            raise GatewayError(msg)
        usage = response.usage
        return EmbeddingResult(
            vectors=vectors,
            model=response.model,
            dimension=len(vectors[0]),
            prompt_tokens=usage.prompt_tokens if usage else None,
        )

    async def aclose(self) -> None:
        await self._client.close()
