"""The "pin this source now" primitive (S13-5).

A pin is a page ID or issue key fetched through the connector's OWN single-item
path — the same ACL walk, version-pinned ref and text extraction the crawl uses.
Pinning is a shortcut past the crawl schedule, never past its rules.

Freshness: `refresh_pins` runs after every successful sync of the connection
(`run_sync` calls it), so a pinned ref re-fetches on the connection's own rhythm.
Without that, the incremental crawl's watermark would skip an unmodified pinned
page forever and the pin would silently freeze at its first fetch.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimo_connectors.base import connection_secret
from estimo_connectors.confluence import ConfluenceConnector
from estimo_connectors.db import Connection, PinnedSource
from estimo_connectors.jira import ISSUE_KEY_RE, JiraConnector
from estimo_connectors.sync import upsert_issue_row

logger = logging.getLogger("estimo.connectors.pins")

# Kinds that HAVE a single-item REST path today. Git repos sync whole-tree.
PINNABLE_KINDS = {"confluence": "page", "jira": "issue"}
MAX_PINS_PER_CONNECTION = 200

_PAGE_ID_RE = re.compile(r"^\d{1,20}$")


def validate_pin_ref(kind: str, ref: str) -> str:
    """Normalize + validate a user-supplied ref; ValueError with a said reason.

    The ref is interpolated into a REST path (Confluence) or a JQL clause (Jira),
    so validation here is an injection boundary, not cosmetics.
    """
    cleaned = ref.strip()
    if kind == "confluence":
        if not _PAGE_ID_RE.match(cleaned):
            msg = f"not a Confluence page id (digits only): {ref!r}"
            raise ValueError(msg)
        return cleaned
    if kind == "jira":
        cleaned = cleaned.upper()
        if not ISSUE_KEY_RE.match(cleaned):
            msg = f"not a Jira issue key (PROJECT-123): {ref!r}"
            raise ValueError(msg)
        return cleaned
    msg = f"connection kind {kind!r} has no single-item fetch path"
    raise ValueError(msg)


async def fetch_pin(session: AsyncSession, connection: Connection, pin: PinnedSource) -> bool:
    """Fetch one pin through the connector's single-item path. True on success.

    Failures land on the pin row (`last_error`), never raise — a broken pin must
    not fail the sync that happens to refresh it. Does not commit.
    """
    config = connection.config or {}
    token = connection_secret(connection)
    try:
        if connection.kind == "confluence":
            if not token:
                raise ValueError("confluence connection requires a credential")
            # Constructed exactly like the crawl (same guards): a pin rides the
            # connection's OWN scoping and ACL configuration, never a laxer one.
            connector = ConfluenceConnector(
                base_url=connection.base_url,
                email=str(config.get("email", "")),
                api_token=token,
                space_keys=tuple(config.get("space_keys", ())),
                default_acl=tuple(connection.acl_keys or ()),
            )
            try:
                document = await connector.page_document(pin.ref)
            finally:
                await connector.aclose()
            if document is None:
                raise ValueError("page has no readable body")
            from estimo_knowledge import upsert_document

            await upsert_document(
                session,
                source_type=document.source_type,
                source_ref=document.source_ref,
                title=document.title,
                text=document.text,
                acl_keys=list(document.acl_keys),
                freshness_at=document.freshness_at,
                authority=document.authority,
            )
        elif connection.kind == "jira":
            if not token:
                raise ValueError("jira connection requires a credential")
            factor = config.get("points_to_pd")
            if not isinstance(factor, int | float) or factor <= 0:
                raise ValueError("jira connection requires config.points_to_pd (> 0)")
            jira = JiraConnector(
                base_url=connection.base_url,
                email=str(config.get("email", "")),
                api_token=token,
            )
            try:
                issue = await jira.pull_issue(pin.ref)
            finally:
                await jira.aclose()
            if issue is None:
                raise ValueError("issue not found (or not visible to this credential)")
            if not await upsert_issue_row(session, issue, float(factor)):
                raise ValueError("issue carries no story points — nothing to import")
        else:
            raise ValueError(f"kind {connection.kind!r} is not pinnable")
    except Exception as exc:  # noqa: BLE001 - recorded on the pin, by design
        pin.last_error = str(exc)[:500]
        logger.warning("pin %s (%s) failed: %s", pin.ref, connection.kind, exc)
        return False
    pin.last_error = None
    pin.last_synced_at = dt.datetime.now(tz=dt.UTC)
    return True


async def refresh_pins(session: AsyncSession, connection: Connection) -> dict[str, Any]:
    """Re-fetch every pin of this connection; commits once at the end."""
    pins = (
        (
            await session.execute(
                select(PinnedSource).where(PinnedSource.connection_id == connection.id)
            )
        )
        .scalars()
        .all()
    )
    refreshed = failed = 0
    for pin in pins:
        if await fetch_pin(session, connection, pin):
            refreshed += 1
        else:
            failed += 1
    if pins:
        await session.commit()
    return {"refreshed": refreshed, "failed": failed}
