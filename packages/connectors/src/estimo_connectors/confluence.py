"""Confluence Cloud crawler (S9-1) — read-only, checkpointed, points-budget compliant.

Web-verified API facts (2026): v2 (`/wiki/api/v2`) covers spaces/pages/versions with
cursor pagination (limit ≤ 250); page READ RESTRICTIONS remain v1-only
(`/wiki/rest/api/content/{id}/restriction`); there is no external webhook surface, so
incremental sync polls the v1 CQL search (`lastmodified >= checkpoint ORDER BY
lastmodified ASC`). Rate limiting is the points model: every returned object costs
budget, so list calls fetch METADATA only and bodies are fetched one page at a time,
pacing slows when `X-RateLimit-NearLimit: true`, and 429/`Retry-After` is always
obeyed (RatePlan).

Auth: customer-created scoped API token on a service account — Basic
`email:api_token`. The token comes from the connection's `secret_env` indirection,
never the database.
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from html import unescape
from typing import Any

import httpx

from estimo_connectors.base import RatePlan, SourceDocument, paced_get

logger = logging.getLogger("estimo.connectors.confluence")

PAGE_LIST_LIMIT = 100  # metadata-only list calls; each returned object costs 1 point
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t ]+")


def storage_to_text(storage_html: str) -> str:
    """Confluence storage format (XHTML) → plain text, dependency-free.

    Block tags become newlines so headings/paragraphs stay separated; entities are
    unescaped; whitespace collapses. Macros lose their chrome but keep their text.
    """
    text = re.sub(r"</(p|h[1-6]|li|tr|div|table)>", "\n", storage_html, flags=re.IGNORECASE)
    text = re.sub(r"<(br|hr)\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = _TAG.sub(" ", text)
    text = unescape(text)
    text = _WS.sub(" ", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _acl_keys(restriction_payload: dict[str, Any], fallback: tuple[str, ...]) -> tuple[str, ...]:
    """Map v1 read restrictions to Estimo ACL keys.

    No read restrictions → the connection's default keys (space-level visibility).
    Restricted → ONLY the enumerated principals may retrieve the chunk
    (SECURITY.md: the pre-filter must never widen access).
    """
    read = restriction_payload.get("read", {}).get("restrictions", {})
    users = [
        f"confluence-user:{item.get('accountId')}"
        for item in read.get("user", {}).get("results", [])
        if item.get("accountId")
    ]
    groups = [
        f"confluence-group:{item.get('id') or item.get('name')}"
        for item in read.get("group", {}).get("results", [])
        if item.get("id") or item.get("name")
    ]
    restricted = tuple(users + groups)
    return restricted if restricted else fallback


class ConfluenceConnector:
    def __init__(
        self,
        *,
        base_url: str,
        email: str,
        api_token: str,
        space_keys: tuple[str, ...] = (),
        default_acl: tuple[str, ...] = ("public",),
        plan: RatePlan | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.space_keys = space_keys
        self.default_acl = default_acl
        self.plan = plan or RatePlan()
        self._client = client or httpx.AsyncClient(
            base_url=self.base_url, auth=(email, api_token), timeout=30.0
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        response = await paced_get(self._client, path, plan=self.plan, params=params)
        if response.headers.get("X-RateLimit-NearLimit", "").lower() == "true":
            # Proactive slowdown: <20% of the hourly points budget remains.
            self.plan.min_interval = min(self.plan.min_interval * 2, 5.0)
        return response

    async def _spaces(self) -> list[dict[str, Any]]:
        spaces: list[dict[str, Any]] = []
        params: dict[str, Any] = {"limit": PAGE_LIST_LIMIT}
        if self.space_keys:
            params["keys"] = ",".join(self.space_keys)
        cursor: str | None = None
        while True:
            if cursor:
                params["cursor"] = cursor
            payload = (await self._get("/wiki/api/v2/spaces", params)).json()
            spaces.extend(payload.get("results", []))
            cursor = _next_cursor(payload)
            if not cursor:
                return spaces

    async def _page_document(
        self, page_id: str, *, space_key: str | None = None
    ) -> SourceDocument | None:
        page = (await self._get(f"/wiki/api/v2/pages/{page_id}", {"body-format": "storage"})).json()
        body = page.get("body", {}).get("storage", {}).get("value", "")
        text = storage_to_text(body)
        if not text:
            return None
        restrictions = (
            await self._get(
                f"/wiki/rest/api/content/{page_id}/restriction",
                {"expand": "restrictions.user,restrictions.group"},
            )
        ).json()
        by_operation = {item.get("operation"): item for item in restrictions.get("results", [])}
        version = page.get("version", {}) or {}
        modified = version.get("createdAt")
        freshness = datetime.fromisoformat(modified) if modified else None
        title = page.get("title", "")
        return SourceDocument(
            source_type="confluence",
            source_ref=f"wiki://{page_id}@{version.get('number', 1)}",
            title=f"[{space_key}] {title}" if space_key else title,
            text=text,
            freshness_at=freshness,
            authority=0.5,
            acl_keys=_acl_keys({"read": by_operation.get("read", {})}, self.default_acl),
        )

    async def crawl(self, checkpoint: dict[str, Any]) -> AsyncIterator[SourceDocument]:
        """Full crawl on an empty checkpoint; CQL incremental afterwards.

        Mutates `checkpoint` in place (`last_modified`, `space_index`) so the caller
        can persist resume state mid-crawl — a first sync may take days.
        """
        last_modified = checkpoint.get("last_modified")
        if last_modified:
            async for document in self._incremental(checkpoint, last_modified):
                yield document
            return

        spaces = await self._spaces()
        start_index = int(checkpoint.get("space_index", 0))
        newest_seen: str | None = None
        for index, space in enumerate(spaces):
            if index < start_index:
                continue
            cursor: str | None = None
            while True:
                params: dict[str, Any] = {
                    "limit": PAGE_LIST_LIMIT,
                    "sort": "-modified-date",
                }
                if cursor:
                    params["cursor"] = cursor
                payload = (
                    await self._get(f"/wiki/api/v2/spaces/{space['id']}/pages", params)
                ).json()
                for item in payload.get("results", []):
                    page_document = await self._page_document(
                        str(item["id"]), space_key=space.get("key")
                    )
                    if page_document is not None:
                        yield page_document
                    modified = (item.get("version") or {}).get("createdAt")
                    if modified and (newest_seen is None or modified > newest_seen):
                        newest_seen = modified
                cursor = _next_cursor(payload)
                if not cursor:
                    break
            checkpoint["space_index"] = index + 1
        if newest_seen:
            checkpoint["last_modified"] = newest_seen
        checkpoint.pop("space_index", None)

    async def _incremental(
        self, checkpoint: dict[str, Any], since_iso: str
    ) -> AsyncIterator[SourceDocument]:
        since = datetime.fromisoformat(since_iso).astimezone(UTC)
        cql = f'type=page and lastmodified >= "{since:%Y/%m/%d %H:%M}" order by lastmodified asc'
        if self.space_keys:
            keys = ", ".join(self.space_keys)
            cql = (
                f"type=page and space in ({keys}) and lastmodified >= "
                f'"{since:%Y/%m/%d %H:%M}" order by lastmodified asc'
            )
        cursor: str | None = None
        newest = since_iso
        while True:
            params: dict[str, Any] = {"cql": cql, "limit": PAGE_LIST_LIMIT}
            if cursor:
                params["cursor"] = cursor
            payload = (await self._get("/wiki/rest/api/search", params)).json()
            for result in payload.get("results", []):
                content = result.get("content") or {}
                page_id = content.get("id")
                if not page_id:
                    continue
                document = await self._page_document(str(page_id))
                if document is not None:
                    yield document
                modified = result.get("lastModified") or (
                    (content.get("version") or {}).get("when")
                )
                if modified and modified > newest:
                    newest = modified
                    checkpoint["last_modified"] = newest
            cursor = _next_cursor(payload)
            if not cursor:
                break


def _next_cursor(payload: dict[str, Any]) -> str | None:
    next_link = (payload.get("_links") or {}).get("next")
    if not next_link:
        return None
    match = re.search(r"[?&]cursor=([^&]+)", next_link)
    return match.group(1) if match else None
