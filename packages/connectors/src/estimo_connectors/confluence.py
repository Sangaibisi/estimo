"""Confluence Cloud crawler (S9-1) — read-only, checkpointed, points-budget compliant.

Web-verified API facts (2026): v2 (`/wiki/api/v2`) covers spaces/pages/versions with
cursor pagination (limit ≤ 250); page READ RESTRICTIONS remain v1-only
(`/wiki/rest/api/content/{id}/restriction`); there is no external webhook surface, so
incremental sync polls the v1 CQL search. Rate limiting is the points model: list
calls fetch METADATA only, bodies one page at a time, pacing slows on
`X-RateLimit-NearLimit` and always obeys 429/`Retry-After` (RatePlan).

ACL discipline (SECURITY.md — the pre-filter must NEVER widen access):
- `space_keys` is REQUIRED: a connection is scoped to spaces whose audience the
  operator states as the connection's ACL keys. An unscoped crawl of "every space
  the service account sees" would silently stamp private-space pages with the
  connection default.
- Confluence view restrictions INHERIT down the page tree, and the v1 endpoint
  returns only restrictions set directly on a page — so the crawler walks
  ANCESTORS until it finds the nearest read restriction; only a chain with no
  restriction at all falls back to the connection's keys.

Auth: customer-created scoped API token on a service account — Basic
`email:api_token`, via the connection's `secret_env` indirection.
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from html import unescape
from typing import Any

import httpx

from estimo_connectors.base import RatePlan, SourceDocument, paced_get

logger = logging.getLogger("estimo.connectors.confluence")

PAGE_LIST_LIMIT = 100  # metadata-only list calls; each returned object costs 1 point

# CQL lastmodified has minute precision and evaluates in the SITE's timezone; the
# incremental window starts this far behind the watermark and re-ingests the overlap
# (upserts make that idempotent) instead of silently skipping edits.
INCREMENTAL_OVERLAP = timedelta(hours=26)

_SPACE_KEY = re.compile(r"^[A-Za-z0-9_~.-]+$")
_CDATA = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t ]+")
# A table cell and the block tags that may wrap its content. Confluence storage format
# wraps cell text in <p>, so cells must be flattened BEFORE the generic block pass.
_CELL = re.compile(r"<(td|th)\b[^>]*>(.*?)</\1\s*>", re.IGNORECASE | re.DOTALL)
_CELL_INNER = re.compile(r"</?(p|div|br|h[1-6])\s*/?>", re.IGNORECASE)
# Sentinels: characters that cannot appear in XHTML text, so they survive the tag pass
# and cannot be forged by page content.
_CELL_SEP = "\x01"
_CDATA_MARK = "\x02{}\x03"
_TRAILING_SEP = re.compile(r"(?:\s*·)+\s*$|^\s*(?:·\s*)+")


def storage_to_text(storage_html: str) -> str:
    """Confluence storage format (XHTML) → plain text, dependency-free.

    Two orderings here are load-bearing, and both were wrong before:

    CDATA bodies (code/noformat macros) are held OUT of the pipeline behind sentinels
    rather than inlined up front. Inlining first fed their contents to the tag-stripper,
    so a rule reading `if (tutar < 100 AND adet > 2)` became `if (tutar 2)` — everything
    between a `<` and the next `>` deleted. In a telco BSS wiki that is precisely where
    the business rules are written.

    Table cells are flattened BEFORE the generic block pass. Confluence wraps cell
    content in `<p>`, so the generic pass turned every cell into its own line and a
    field table lost the association between a field and its type: `musteri_no` and
    `VARCHAR(20)` ended up on separate lines, unsearchable as a pair and meaningless to
    a human reading the retrieved text. Cells now join with a separator and `</tr>`
    remains the only row boundary.
    """
    held: list[str] = []

    def _hold(match: re.Match[str]) -> str:
        held.append(match.group(1))
        return _CDATA_MARK.format(len(held) - 1)

    text = _CDATA.sub(_hold, storage_html)
    text = _CELL.sub(lambda m: f"{_CELL_INNER.sub(' ', m.group(2))}{_CELL_SEP}", text)
    text = re.sub(r"</(p|h[1-6]|li|tr|div|table)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<(br|hr)\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = _TAG.sub(" ", text)
    text = unescape(text)
    # Restore AFTER unescape: a code sample's `&amp;` is literal text, and unescaping it
    # would silently rewrite the sample.
    for index, body in enumerate(held):
        text = text.replace(_CDATA_MARK.format(index), body)
    text = text.replace(_CELL_SEP, " · ")
    text = _WS.sub(" ", text)
    # A trailing cell separator on every row, and rows that were only empty cells.
    lines = (_TRAILING_SEP.sub("", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def _parse_when(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).astimezone(UTC)
    except ValueError:
        return None


def _direct_read_principals(restriction_payload: dict[str, Any]) -> tuple[str, ...]:
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
    return tuple(users + groups)


class ConfluenceConnector:
    def __init__(
        self,
        *,
        base_url: str,
        email: str,
        api_token: str,
        space_keys: tuple[str, ...],
        default_acl: tuple[str, ...],
        plan: RatePlan | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not space_keys:
            raise ValueError(
                "confluence connections require explicit space_keys — an unscoped "
                "crawl would ingest every space the service account can see"
            )
        for key in space_keys:
            if not _SPACE_KEY.match(key):
                raise ValueError(f"invalid confluence space key: {key!r}")
        if not default_acl:
            raise ValueError("confluence connections require explicit acl_keys")
        self.base_url = base_url.rstrip("/")
        self.space_keys = space_keys
        self.default_acl = default_acl
        self.plan = plan or RatePlan()
        self._client = client or httpx.AsyncClient(
            base_url=self.base_url, auth=(email, api_token), timeout=30.0
        )
        # page_id -> direct read principals (() = none); bounds the ancestor walks.
        self._restriction_cache: dict[str, tuple[str, ...]] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        return await paced_get(self._client, path, plan=self.plan, params=params)

    async def _paginate(self, path: str, params: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        """Yield result payloads across pages by following `_links.next` VERBATIM —
        re-extracting the cursor would double-encode it (base64 padding)."""
        response = await self._get(path, params)
        seen: set[str] = set()
        while True:
            payload = response.json()
            yield payload
            next_link = (payload.get("_links") or {}).get("next")
            if not next_link:
                return
            if next_link in seen:
                raise RuntimeError(f"pagination loop detected at {next_link}")
            seen.add(next_link)
            response = await self._get(next_link, None)

    async def _spaces(self) -> list[dict[str, Any]]:
        spaces: list[dict[str, Any]] = []
        params: dict[str, Any] = {
            "limit": PAGE_LIST_LIMIT,
            "keys": ",".join(self.space_keys),
            # Deterministic order: the checkpoint's space ordinal must mean the
            # same space on resume.
            "sort": "id",
        }
        async for payload in self._paginate("/wiki/api/v2/spaces", params):
            spaces.extend(payload.get("results", []))
        return spaces

    async def _direct_restrictions(self, page_id: str) -> tuple[str, ...]:
        cached = self._restriction_cache.get(page_id)
        if cached is not None:
            return cached
        payload = (
            await self._get(
                f"/wiki/rest/api/content/{page_id}/restriction",
                {"expand": "restrictions.user,restrictions.group"},
            )
        ).json()
        by_operation = {item.get("operation"): item for item in payload.get("results", [])}
        principals = _direct_read_principals({"read": by_operation.get("read", {})})
        self._restriction_cache[page_id] = principals
        return principals

    async def _effective_acl(self, page_id: str, parent_id: str | None) -> tuple[str, ...]:
        """Nearest read restriction walking UP the tree; connection keys only when
        the whole chain is unrestricted (restrictions inherit downward)."""
        principals = await self._direct_restrictions(page_id)
        if principals:
            return principals
        current = parent_id
        for _ in range(64):  # cycle / hierarchy-depth guard
            if not current:
                return self.default_acl
            principals = await self._direct_restrictions(current)
            if principals:
                return principals
            parent = (await self._get(f"/wiki/api/v2/pages/{current}")).json()
            current = parent.get("parentId")
        return self.default_acl

    async def page_document(
        self, page_id: str, *, space_key: str | None = None
    ) -> SourceDocument | None:
        """Public single-page fetch — the S13-5 pin primitive rides exactly the
        crawl's own path: same ACL walk, same version-pinned ref, same text
        extraction. A pin must never be a second, laxer ingestion route."""
        return await self._page_document(page_id, space_key=space_key)

    async def _page_document(
        self, page_id: str, *, space_key: str | None = None
    ) -> SourceDocument | None:
        page = (await self._get(f"/wiki/api/v2/pages/{page_id}", {"body-format": "storage"})).json()
        body = page.get("body", {}).get("storage", {}).get("value", "")
        text = storage_to_text(body)
        if not text:
            return None
        acl = await self._effective_acl(page_id, page.get("parentId"))
        version = page.get("version", {}) or {}
        title = page.get("title", "")
        return SourceDocument(
            source_type="confluence",
            source_ref=f"wiki://{page_id}@{version.get('number', 1)}",
            title=f"[{space_key}] {title}" if space_key else title,
            text=text,
            freshness_at=_parse_when(version.get("createdAt")),
            authority=0.5,
            acl_keys=acl,
        )

    async def crawl(self, checkpoint: dict[str, Any]) -> AsyncIterator[SourceDocument]:
        """Full crawl on an empty checkpoint; CQL incremental afterwards.

        Mutates `checkpoint` in place (`last_modified` ISO-UTC watermark,
        `space_index` ordinal over the id-sorted space list) so the caller can
        persist resume state mid-crawl — a first sync may take days. An interrupted
        full crawl leaves `space_index` behind and resumes as a full crawl; only a
        COMPLETED full crawl switches to incremental mode.
        """
        last_modified = checkpoint.get("last_modified")
        if last_modified and "space_index" not in checkpoint:
            async for document in self._incremental(checkpoint, str(last_modified)):
                yield document
            return

        spaces = await self._spaces()
        start_index = int(checkpoint.get("space_index", 0))
        newest_seen = _parse_when(str(last_modified)) if last_modified else None
        for index, space in enumerate(spaces):
            if index < start_index:
                continue
            checkpoint["space_index"] = index
            params: dict[str, Any] = {"limit": PAGE_LIST_LIMIT, "sort": "-modified-date"}
            async for payload in self._paginate(f"/wiki/api/v2/spaces/{space['id']}/pages", params):
                for item in payload.get("results", []):
                    page_document = await self._page_document(
                        str(item["id"]), space_key=space.get("key")
                    )
                    if page_document is not None:
                        yield page_document
                    modified = _parse_when((item.get("version") or {}).get("createdAt"))
                    if modified and (newest_seen is None or modified > newest_seen):
                        newest_seen = modified
                        checkpoint["last_modified"] = modified.isoformat()
        if newest_seen:
            checkpoint["last_modified"] = newest_seen.isoformat()
        checkpoint.pop("space_index", None)

    async def _incremental(
        self, checkpoint: dict[str, Any], since_iso: str
    ) -> AsyncIterator[SourceDocument]:
        watermark = _parse_when(since_iso)
        if watermark is None:
            raise ValueError(f"unparseable checkpoint watermark: {since_iso!r}")
        since = watermark - INCREMENTAL_OVERLAP
        keys = ", ".join(f'"{key}"' for key in self.space_keys)
        cql = (
            f"type=page and space in ({keys}) and "
            f'lastmodified >= "{since:%Y/%m/%d %H:%M}" order by lastmodified asc'
        )
        newest = watermark
        params: dict[str, Any] = {"cql": cql, "limit": PAGE_LIST_LIMIT}
        async for payload in self._paginate("/wiki/rest/api/search", params):
            for result in payload.get("results", []):
                content = result.get("content") or {}
                page_id = content.get("id")
                if not page_id:
                    continue
                document = await self._page_document(str(page_id))
                if document is not None:
                    yield document
                modified = _parse_when(
                    result.get("lastModified") or (content.get("version") or {}).get("when")
                )
                if modified and modified > newest:
                    newest = modified
                    checkpoint["last_modified"] = newest.isoformat()
