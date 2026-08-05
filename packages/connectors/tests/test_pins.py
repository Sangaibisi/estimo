"""The pin primitive (S13-5): validation, single-item fetch, re-sync membership."""

from __future__ import annotations

import pytest
import respx
from estimo_connectors import Connection
from estimo_connectors.db import PinnedSource
from estimo_connectors.pins import fetch_pin, refresh_pins, validate_pin_ref
from estimo_knowledge import KnowledgeChunk, LedgerEntryRow
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

BASE = "https://aurora.atlassian.net"


class TestValidateRef:
    def test_confluence_page_ids_are_digits_only(self) -> None:
        assert validate_pin_ref("confluence", " 12345 ") == "12345"
        with pytest.raises(ValueError, match="page id"):
            validate_pin_ref("confluence", "12345 OR 1=1")
        with pytest.raises(ValueError, match="page id"):
            validate_pin_ref("confluence", "../secrets")

    def test_jira_keys_fold_to_uppercase_and_reject_jql(self) -> None:
        assert validate_pin_ref("jira", "aur-42") == "AUR-42"
        with pytest.raises(ValueError, match="issue key"):
            validate_pin_ref("jira", 'AUR-42" OR project = SECRET')

    def test_git_kinds_are_not_pinnable(self) -> None:
        with pytest.raises(ValueError, match="single-item"):
            validate_pin_ref("github", "README.md")


def _page_payload(page_id: str, title: str, *, version: int = 3) -> dict[str, object]:
    return {
        "id": page_id,
        "title": title,
        "version": {"number": version, "createdAt": "2026-07-01T10:00:00Z"},
        "body": {"storage": {"value": "<p>Taksitli fatura kırılımı billing-core.</p>"}},
    }


def _no_restrictions() -> dict[str, object]:
    return {
        "results": [
            {
                "operation": "read",
                "restrictions": {"user": {"results": []}, "group": {"results": []}},
            }
        ]
    }


@pytest.mark.db
class TestFetchPin:
    @pytest.fixture
    async def clean(self, session: AsyncSession, clean_tables: None) -> AsyncSession:
        await session.execute(text("TRUNCATE connections, sync_runs, pinned_sources CASCADE"))
        await session.commit()
        return session

    @respx.mock
    async def test_confluence_pin_lands_acl_walked_and_version_pinned(
        self, clean: AsyncSession
    ) -> None:
        session = clean
        connection = Connection(
            kind="confluence",
            name="wiki",
            base_url=BASE,
            config={"email": "svc@aurora.example", "space_keys": ["AUR"]},
            secret="plain:token",
            acl_keys=["space:AUR"],
        )
        session.add(connection)
        await session.commit()
        pin = PinnedSource(connection_id=connection.id, kind="page", ref="777")
        session.add(pin)
        await session.commit()

        respx.get(f"{BASE}/wiki/api/v2/pages/777").respond(
            200, json=_page_payload("777", "Pinlenen sayfa", version=9)
        )
        respx.get(f"{BASE}/wiki/rest/api/content/777/restriction").respond(
            200, json=_no_restrictions()
        )

        assert await fetch_pin(session, connection, pin)
        await session.commit()
        chunk = await session.scalar(
            select(KnowledgeChunk).where(KnowledgeChunk.source_ref == "wiki://777@9")
        )
        assert chunk is not None, "the pin did not land version-pinned"
        assert chunk.acl_keys == ["space:AUR"], "the pin bypassed the ACL walk"
        assert pin.last_synced_at is not None and pin.last_error is None

    @respx.mock
    async def test_jira_pin_writes_a_ledger_row(self, clean: AsyncSession) -> None:
        session = clean
        connection = Connection(
            kind="jira",
            name="jira",
            base_url=BASE,
            config={"email": "svc@aurora.example", "points_to_pd": 0.8},
            secret="plain:token",
        )
        session.add(connection)
        await session.commit()
        pin = PinnedSource(connection_id=connection.id, kind="issue", ref="AUR-42")
        session.add(pin)
        await session.commit()

        respx.get(f"{BASE}/rest/api/3/field").respond(
            200,
            json=[
                {"id": "customfield_10016", "name": "Story Points", "schema": {"type": "number"}}
            ],
        )
        respx.get(f"{BASE}/rest/api/3/search/jql").respond(
            200,
            json={
                "issues": [
                    {
                        "key": "AUR-42",
                        "fields": {
                            "summary": "Pinlenen iş",
                            "description": None,
                            "customfield_10016": 5,
                        },
                    }
                ],
                "isLast": True,
            },
        )

        assert await fetch_pin(session, connection, pin)
        await session.commit()
        row = await session.scalar(
            select(LedgerEntryRow).where(LedgerEntryRow.origin_ref == "jira://AUR-42")
        )
        assert row is not None
        assert float(row.estimate_single or 0) == 4.0  # 5 points × 0.8

    @respx.mock
    async def test_a_failing_pin_records_the_error_and_does_not_raise(
        self, clean: AsyncSession
    ) -> None:
        session = clean
        connection = Connection(
            kind="confluence",
            name="wiki2",
            base_url=BASE,
            config={"email": "svc@aurora.example", "space_keys": ["AUR"]},
            secret="plain:token",
            acl_keys=["space:AUR"],
        )
        session.add(connection)
        await session.commit()
        pin = PinnedSource(connection_id=connection.id, kind="page", ref="404404")
        session.add(pin)
        await session.commit()

        respx.get(f"{BASE}/wiki/api/v2/pages/404404").respond(404, json={})
        assert not await fetch_pin(session, connection, pin)
        assert pin.last_error
        assert pin.last_synced_at is None

    @respx.mock
    async def test_refresh_pins_counts_both_outcomes(self, clean: AsyncSession) -> None:
        session = clean
        connection = Connection(
            kind="confluence",
            name="wiki3",
            base_url=BASE,
            config={"email": "svc@aurora.example", "space_keys": ["AUR"]},
            secret="plain:token",
            acl_keys=["space:AUR"],
        )
        session.add(connection)
        await session.commit()
        session.add(PinnedSource(connection_id=connection.id, kind="page", ref="1"))
        session.add(PinnedSource(connection_id=connection.id, kind="page", ref="2"))
        await session.commit()

        respx.get(f"{BASE}/wiki/api/v2/pages/1").respond(200, json=_page_payload("1", "Sayfa bir"))
        respx.get(f"{BASE}/wiki/rest/api/content/1/restriction").respond(
            200, json=_no_restrictions()
        )
        respx.get(f"{BASE}/wiki/api/v2/pages/2").respond(500, json={})

        stats = await refresh_pins(session, connection)
        assert stats == {"refreshed": 1, "failed": 1}
