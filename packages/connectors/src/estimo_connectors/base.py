"""Connector core (S9): document model, pacing, checkpoints, secret indirection.

Connectors are READ-ONLY crawlers that turn external sources into
`knowledge_chunks` rows with honest metadata: the source's own modified time as
freshness (never ingestion time), ACL keys stamped from the connection, and
checkpointed cursors so a first sync that takes days survives restarts.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import httpx

logger = logging.getLogger("estimo.connectors")


@dataclass(frozen=True)
class SourceDocument:
    """One ingestable unit from an external source."""

    source_type: str
    source_ref: str
    title: str
    text: str
    freshness_at: datetime | None
    authority: float
    acl_keys: tuple[str, ...]


class Connector(Protocol):
    """A checkpointed crawl: yields documents, mutates `checkpoint` in place as it
    advances so the caller can persist resume state at any moment."""

    def crawl(self, checkpoint: dict[str, Any]) -> AsyncIterator[SourceDocument]: ...


def resolve_secret(secret_env: str | None) -> str | None:
    """Connections store the NAME of an env var, never the secret (SECURITY.md)."""
    if not secret_env:
        return None
    value = os.getenv(secret_env)
    if value is None:
        raise LookupError(f"secret env var {secret_env!r} is not set on this container")
    return value


class RatePlan:
    """Compliant pacing for cost-budgeted APIs (Atlassian's points model).

    Mechanisms, all mandatory for a days-long first sync:
    - a floor delay between requests (steady, budget-friendly cadence);
    - proactive slowdown while the server signals `X-RateLimit-NearLimit`, decaying
      back to the base cadence once the budget recovers;
    - full obedience to 429/`Retry-After` (the SERVER's value wins, up to a sanity
      ceiling) with capped exponential fallback when it does not say how long.
    """

    RETRY_AFTER_CEILING = 900.0  # honor the server up to 15 minutes

    def __init__(self, *, min_interval: float = 0.3, max_backoff: float = 120.0) -> None:
        self.base_interval = min_interval
        self.min_interval = min_interval
        self.max_backoff = max_backoff
        self._backoff = 1.0

    async def pace(self) -> None:
        await asyncio.sleep(self.min_interval)

    def observe_budget(self, response: httpx.Response) -> None:
        """Adjust cadence from budget headers: slow near the limit, recover after."""
        near = response.headers.get("X-RateLimit-NearLimit", "").lower() == "true"
        if near:
            self.min_interval = min(self.min_interval * 2, 5.0)
        elif self.min_interval > self.base_interval:
            self.min_interval = max(self.base_interval, self.min_interval / 2)

    async def on_response(self, response: httpx.Response) -> bool:
        """Returns True when the request should be retried after backing off."""
        if response.status_code != 429:
            self._backoff = 1.0
            self.observe_budget(response)
            return False
        retry_after = response.headers.get("Retry-After")
        try:
            delay = float(retry_after) if retry_after else self._backoff
        except ValueError:
            delay = self._backoff
        delay = min(delay, self.RETRY_AFTER_CEILING)
        self._backoff = min(self._backoff * 2, self.max_backoff)
        logger.warning("rate limited; sleeping %.1fs", delay)
        await asyncio.sleep(delay)
        return True


async def paced_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    plan: RatePlan,
    params: dict[str, Any] | None = None,
    max_attempts: int = 6,
) -> httpx.Response:
    """GET with pacing + 429 obedience; raises for non-2xx after retries."""
    for _ in range(max_attempts):
        await plan.pace()
        response = await client.get(url, params=params)
        if await plan.on_response(response):
            continue
        response.raise_for_status()
        return response
    raise httpx.HTTPError(f"rate limit never lifted for {url}")
