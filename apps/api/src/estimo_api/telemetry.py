"""Optional Langfuse forwarding (S8-4).

A complete no-op unless LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY (and typically
LANGFUSE_HOST, pointing at the self-hosted `observability` compose profile) are set —
Estimo runs fully without observability configured. When active, UI telemetry events
become Langfuse events and anchoring deltas become scores.

Metadata-only is ENFORCED here, not assumed (same discipline as the gateway log
hook): numbers and booleans pass; strings pass only when they look like identifiers
(`WI-G-01`, `timesheet`) — free text, and therefore BRD or prompt bodies, never
leaves the process regardless of what a client stuffed into an event payload. The
full payload still lands in the local `ui_events` table.
"""

from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from typing import Any

logger = logging.getLogger("estimo.api.telemetry")

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:/-]{1,64}$")


def sanitize_metadata(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Keep numbers/bools and identifier-shaped strings; drop everything else."""
    clean: dict[str, Any] = {}
    for key, value in (payload or {}).items():
        if not isinstance(key, str) or not _IDENTIFIER.match(key):
            continue
        if (
            isinstance(value, bool | int | float)
            or isinstance(value, str)
            and _IDENTIFIER.match(value)
        ):
            clean[key] = value
    return clean


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
            metadata={"estimate_id": estimate_id, **sanitize_metadata(payload)},
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
