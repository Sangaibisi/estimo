"""Deterministic OpenAI-compatible mock endpoint — test/dev only, never production.

Runs as the `mock-llm` compose profile service so the gateway smoke check has a target
without any real LLM. Shapes mirror the OpenAI chat-completions and embeddings
responses minimally.
"""

from __future__ import annotations

import hashlib
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Estimo Mock LLM", docs_url=None)

MOCK_DIMENSION = 8


class ChatRequest(BaseModel):
    model: str
    messages: list[dict[str, Any]]


class EmbeddingsRequest(BaseModel):
    model: str
    input: str | list[str]


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


_IMPACT_FINALIZE = (
    '{"action": "finalize", "analysis": {"repos": [], "modules": [], '
    '"integration_points": [], "discovery_risks": [], '
    '"composition": [{"discipline": "frontend", "share": 0.5, "rationale": "mock"}, '
    '{"discipline": "backend", "share": 0.5, "rationale": "mock"}], '
    '"confidence": "low"}}'
)


def _scripted_reply(messages: list[dict[str, Any]]) -> str | None:
    """Protocol-aware canned replies, keyed on prompt sentinels.

    The impact worker (S13-2) speaks a JSON-action protocol; a free-text reply would
    cost it two strikes per work item before it falls back. The mock finalizes
    immediately with an empty-but-valid analysis (claims need real evidence the mock
    cannot cite; an empty analysis exercises the whole loop + verifier honestly).
    The vetting and no-analog legs (S13-4) get minimal valid replies the same way:
    "everything comparable" and a deliberately wide band."""
    joined = " ".join(str(m.get("content", "")) for m in messages)
    if "ESTIMO-IMPACT-PROTOCOL" in joined:
        return _IMPACT_FINALIZE
    if "ESTIMO-VET" in joined:
        return '{"verdicts": []}'
    if "ESTIMO-PROPOSE" in joined:
        return (
            '{"optimistic": 2, "likely": 5, "pessimistic": 20, '
            '"rationale": "mock önerisi", "assumptions": ["mock varsayımı"]}'
        )
    return None


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest) -> dict[str, Any]:
    last_user = next(
        (m.get("content", "") for m in reversed(request.messages) if m.get("role") == "user"),
        "",
    )
    text = _scripted_reply(request.messages)
    if text is None:
        text = "ok" if "ok" in str(last_user).lower() else f"mock response to: {last_user}"[:200]
    return {
        "id": "chatcmpl-mock-1",
        "object": "chat.completion",
        "created": 1_700_000_000,
        "model": request.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    }


def _vector_for(text: str) -> list[float]:
    digest = hashlib.sha256(text.encode()).digest()
    return [round(b / 255, 6) for b in digest[:MOCK_DIMENSION]]


@app.post("/v1/embeddings")
async def embeddings(request: EmbeddingsRequest) -> dict[str, Any]:
    texts = [request.input] if isinstance(request.input, str) else request.input
    return {
        "object": "list",
        "model": request.model,
        "data": [
            {"object": "embedding", "index": i, "embedding": _vector_for(t)}
            for i, t in enumerate(texts)
        ],
        "usage": {"prompt_tokens": len(texts), "total_tokens": len(texts)},
    }
