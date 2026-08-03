"""Jira pull (post-410 endpoints) + canonical curation flow."""

import httpx
import pytest
import respx
from estimo_connectors import JiraConnector, RatePlan, approve, generate_candidate
from estimo_knowledge import KnowledgeChunk, lexical_chunk_ids
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

JIRA = "https://aurora.atlassian.net"


@respx.mock
async def test_jira_pull_discovers_points_field_and_paginates() -> None:
    respx.get(f"{JIRA}/rest/api/3/field").respond(
        json=[
            {
                "id": "customfield_10016",
                "name": "Story point estimate",
                "schema": {"type": "number"},
            },
            {"id": "customfield_10999", "name": "Story Points", "schema": {"type": "number"}},
            {"id": "customfield_10777", "name": "Story Points", "schema": {"type": "string"}},
            {"id": "summary", "name": "Summary", "schema": {"type": "string"}},
        ]
    )
    search = respx.get(f"{JIRA}/rest/api/3/search/jql")
    search.side_effect = [
        httpx.Response(
            200,
            json={
                "issues": [
                    {
                        "key": "AUR-1",
                        "fields": {
                            "summary": "Taksit epic",
                            "issuetype": {"name": "Epic"},
                            "status": {"name": "Done"},
                            "customfield_10999": 8,
                            "description": {
                                "type": "doc",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [{"type": "text", "text": "Kırılım detayı"}],
                                    }
                                ],
                            },
                        },
                    }
                ],
                "nextPageToken": "t2",
            },
        ),
        httpx.Response(
            200,
            json={
                "issues": [
                    {
                        "key": "AUR-2",
                        "fields": {
                            "summary": "Story",
                            "issuetype": {"name": "Story"},
                            "parent": {"key": "AUR-1"},
                            "customfield_10016": 3,
                        },
                    }
                ],
                "isLast": True,
            },
        ),
    ]

    connector = JiraConnector(
        base_url=JIRA, email="svc@aurora.example", api_token="t", plan=RatePlan(min_interval=0)
    )
    issues = await connector.pull_issues(jql="issuetype in (Epic, Story)")
    await connector.aclose()

    assert [issue.key for issue in issues] == ["AUR-1", "AUR-2"]
    assert issues[0].story_points == 8  # discovered field, never hardcoded
    assert issues[0].description is not None and "Kırılım detayı" in issues[0].description
    assert issues[1].parent_key == "AUR-1"
    assert issues[1].story_points == 3
    # The string-typed lookalike field must not be treated as story points.
    fields_param = search.calls[0].request.url.params["fields"]
    assert "customfield_10777" not in fields_param


@pytest.mark.db
class TestCanonicalCuration:
    @pytest.fixture
    async def seeded_chunks(self, session: AsyncSession, clean_tables: None) -> AsyncSession:
        from estimo_knowledge import upsert_generated_chunks

        await session.execute(text("TRUNCATE canonical_pages"))
        await session.commit()
        await upsert_generated_chunks(
            session,
            [
                (
                    "module/billing-core",
                    "billing-core",
                    "Taksitli fatura kırılımı billing-core modülünde hesaplanır.",
                ),
                (
                    "module/crm-suite",
                    "crm-suite",
                    "Müşteri kayıtları crm-suite üzerinden yönetilir.",
                ),
            ],
        )
        return session

    async def test_draft_stays_out_of_retrieval_until_approved(
        self, seeded_chunks: AsyncSession
    ) -> None:
        page = await generate_candidate(seeded_chunks, topic="taksitli fatura kırılımı")
        assert page.status == "draft"
        assert page.source_refs  # provenance recorded
        assert "billing-core" in page.body

        canonical_chunks = list(
            (
                await seeded_chunks.execute(
                    select(KnowledgeChunk).where(KnowledgeChunk.source_type == "canonical")
                )
            ).scalars()
        )
        assert canonical_chunks == []  # the human gate is real

        approved = await approve(seeded_chunks, page, approver="D. Aksoy")
        assert approved.status == "approved" and approved.version == 2

        canonical_chunks = list(
            (
                await seeded_chunks.execute(
                    select(KnowledgeChunk).where(KnowledgeChunk.source_type == "canonical")
                )
            ).scalars()
        )
        assert len(canonical_chunks) == 1
        assert float(canonical_chunks[0].authority) == 0.95

        # Approved canonical content ranks in retrieval with top authority.
        ids = await lexical_chunk_ids(
            seeded_chunks, "taksitli fatura kırılımı", acl_keys=["public"], limit=5
        )
        assert canonical_chunks[0].id in ids

    async def test_acl_prefilter_never_widens(self, seeded_chunks: AsyncSession) -> None:
        """S9-3 regression: a chunk with restricted ACL keys is invisible to callers
        holding other keys — mechanically, not by convention."""
        from estimo_knowledge import upsert_document

        await upsert_document(
            seeded_chunks,
            source_type="confluence",
            source_ref="wiki://secret-page@1",
            title="Gizli taksit planı",
            text="Taksitli fatura kırılımı için gizli plan.",
            acl_keys=["confluence-group:finans"],
        )
        await seeded_chunks.commit()

        public_ids = await lexical_chunk_ids(
            seeded_chunks, "taksitli fatura", acl_keys=["public"], limit=10
        )
        secret = await seeded_chunks.scalar(
            select(KnowledgeChunk.id).where(KnowledgeChunk.source_ref == "wiki://secret-page@1")
        )
        assert secret is not None
        assert secret not in public_ids

        finance_ids = await lexical_chunk_ids(
            seeded_chunks,
            "taksitli fatura",
            acl_keys=["confluence-group:finans"],
            limit=10,
        )
        assert secret in finance_ids
