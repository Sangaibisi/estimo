"""Optional Langfuse forwarding (S8-4).

A complete no-op unless LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY (and typically
LANGFUSE_HOST, pointing at the self-hosted `observability` compose profile) are set —
Estimo runs fully without observability configured. When active, UI telemetry events
become Langfuse events and anchoring deltas become scores; bodies of BRDs or prompts
are NEVER forwarded (metadata only, same discipline as the gateway log hook).
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

logger = logging.getLogger("estimo.api.telemetry")


@lru_cache(maxsize=1)
def _client() -> Any | None:
    if not (os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
        return None
    try:
        from langfuse import get_client
    except ImportError:  # pragma: no cover - dependency is installed by default
        logger.warning("LANGFUSE_* set but the langfuse package is unavailable")
        return None
    logger.info("langfuse telemetry forwarding active")
    return get_client()


def reset_cached_client() -> None:
    """Test hook: re-evaluate the environment on the next emit."""
    _client.cache_clear()


def emit_event(kind: str, estimate_id: str, payload: dict[str, Any] | None = None) -> bool:
    """Forward one telemetry event. Returns whether it was forwarded (for tests)."""
    client = _client()
    if client is None:
        return False
    try:
        client.create_event(
            name=f"estimo.{kind}",
            metadata={"estimate_id": estimate_id, **(payload or {})},
        )
    except Exception:
        logger.warning("langfuse event forward failed", exc_info=True)
        return False
    return True


def emit_score(name: str, value: float, estimate_id: str) -> bool:
    """Forward one numeric score (e.g. the anchoring delta at reveal time)."""
    client = _client()
    if client is None:
        return False
    try:
        client.create_score(
            name=name, value=value, data_type="NUMERIC", metadata={"estimate_id": estimate_id}
        )
    except Exception:
        logger.warning("langfuse score forward failed", exc_info=True)
        return False
    return True
