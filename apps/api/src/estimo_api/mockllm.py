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


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest) -> dict[str, Any]:
    last_user = next(
        (m.get("content", "") for m in reversed(request.messages) if m.get("role") == "user"),
        "",
    )
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
