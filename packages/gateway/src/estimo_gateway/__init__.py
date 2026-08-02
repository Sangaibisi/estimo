"""Estimo gateway — the single place model I/O happens (ADR-0001).

The `openai` package is used here strictly as an OpenAI-compatible *protocol* client
pointed at a configurable base URL (LiteLLM proxy at deployments). No other package in
this repository may import a provider SDK; CI and tests enforce that.
"""

from estimo_gateway.client import (
    CompletionResult,
    EmbeddingResult,
    GatewayClient,
    GatewayConnectionError,
    GatewayError,
    GatewayRateLimitedError,
    GatewayStatusError,
    UnknownStageError,
)
from estimo_gateway.config import GatewayConfig, GatewaySettings

__all__ = [
    "CompletionResult",
    "EmbeddingResult",
    "GatewayClient",
    "GatewayConfig",
    "GatewayConnectionError",
    "GatewayError",
    "GatewayRateLimitedError",
    "GatewaySettings",
    "GatewayStatusError",
    "UnknownStageError",
]
