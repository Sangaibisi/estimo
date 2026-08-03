"""DB-backed regression tests for the S9 review findings on sync orchestration."""

import os
import subprocess
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from estimo_connectors import Connection, SyncRun, run_sync
from estimo_connectors.sync import _last_checkpoint, _workdir_name, sweep_interrupted_runs
from estimo_knowledge import KnowledgeChunk
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.db


def _init_git_repo(path: Path, *, second_module: bool = False) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    (path / "billing").mkdir()
    (path / "billing" / "Billing.java").write_text("public class Billing {}\n")
    if second_module:
        (path / "crm").mkdir()
        (path / "crm" / "Crm.java").write_text("public class Crm {}\n")
    for cmd in (["add", "."], ["commit", "-q", "-m", "init"]):
        subprocess.run(
            ["git", "-c", "user.email=t@e.local", "-c", "user.name=T", "-C", str(path), *cmd],
            check=True,
        )


@pytest.fixture
async def clean(session: AsyncSession, clean_tables: None) -> AsyncSession:
    await session.execute(text("TRUNCATE connections, sync_runs, canonical_pages CASCADE"))
    await session.commit()
    return session


def test_workdir_name_is_path_safe() -> None:
    conn = Connection(id=uuid.uuid4(), kind="git", name="../../etc/passwd", base_url="x")
    name = _workdir_name(conn)
    assert "/" not in name and ".." not in name
    assert name.startswith(("etc_passwd-", "_etc_passwd-"))


async def test_interrupted_run_sweep_unblocks_and_resume_reads_failed_checkpoint(
    clean: AsyncSession,
) -> None:
    session = clean
    conn = Connection(kind="git", name="c1", base_url="file:///x")
    session.add(conn)
    await session.commit()

    # A crashed run left 'running' with partial progress.
    stuck = SyncRun(connection_id=conn.id, status="running", checkpoint={"head_sha": "deadbeef"})
    session.add(stuck)
    await session.commit()

    swept = await sweep_interrupted_runs(session)
    assert swept == 1
    # Its checkpoint is still the newest progress and IS used for resume, even
    # though the run is 'failed'.
    resumed = await _last_checkpoint(session, conn)
    assert resumed == {"head_sha": "deadbeef"}


async def test_git_sync_prunes_deleted_modules(clean: AsyncSession, tmp_path: Path) -> None:
    session = clean
    origin = tmp_path / "origin"
    origin.mkdir()
    _init_git_repo(origin, second_module=True)
    conn = Connection(
        kind="git", name="prune-me", base_url=f"file://{origin}", config={"branch": "main"}
    )
    session.add(conn)
    await session.commit()

    first = await run_sync(session, conn, repos_dir=tmp_path / "work")
    assert first.status == "succeeded", first.error
    before = list(
        (
            await session.execute(
                select(KnowledgeChunk.source_ref).where(KnowledgeChunk.source_type == "code-wiki")
            )
        ).scalars()
    )
    assert any("crm" in ref.lower() for ref in before)

    # Delete a whole module → its chunk must leave retrieval on next sync.
    (origin / "crm" / "Crm.java").unlink()
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@e.local",
            "-c",
            "user.name=T",
            "-C",
            str(origin),
            "commit",
            "-qam",
            "drop crm",
        ],
        check=True,
    )
    second = await run_sync(session, conn, repos_dir=tmp_path / "work")
    assert second.status == "succeeded", second.error
    assert second.stats is not None and second.stats.get("pruned", 0) >= 1


async def test_jira_kind_requires_points_conversion(clean: AsyncSession) -> None:
    session = clean
    conn = Connection(
        kind="jira",
        name="jira-conn",
        base_url="https://aurora.atlassian.net",
        config={"email": "svc@aurora.example"},
        secret_env="PATH",  # any set env var; the run fails earlier on points_to_pd
    )
    session.add(conn)
    await session.commit()
    run = await run_sync(session, conn, repos_dir=None)
    assert run.status == "failed"
    assert "points_to_pd" in (run.error or "")


async def test_canonical_approve_refuses_mixed_audience_without_explicit_acl(
    clean: AsyncSession,
) -> None:
    session = clean
    from estimo_knowledge import upsert_document

    await upsert_document(
        session,
        source_type="confluence",
        source_ref="wiki://a@1",
        title="A",
        text="Taksitli fatura kırılımı public tarafı.",
        acl_keys=["public"],
    )
    await upsert_document(
        session,
        source_type="confluence",
        source_ref="wiki://b@1",
        title="B",
        text="Taksitli fatura kırılımı gizli tarafı.",
        acl_keys=["confluence-group:finans"],
    )
    await session.commit()

    from estimo_connectors import approve, generate_candidate

    page = await generate_candidate(
        session, topic="taksitli fatura kırılımı", acl_keys=["public", "confluence-group:finans"]
    )
    # PUBLIC_ACL is held by every reader, so it constrains nothing: the audience that
    # can read BOTH sources is exactly the restricted one. This used to raise and hand
    # the approver a free-text audience instead — the widening this test now guards.
    approved = await approve(session, page, approver="D. Aksoy")
    chunk = await session.scalar(
        select(KnowledgeChunk).where(KnowledgeChunk.source_type == "canonical")
    )
    assert chunk is not None and chunk.acl_keys == ["confluence-group:finans"]
    # Stable source_ref (no @version): re-approval replaces, never accumulates.
    assert chunk.source_ref == "canonical://taksitli fatura kırılımı"
    assert approved.version == 2


async def test_canonical_reapproval_does_not_accumulate_versions(
    clean: AsyncSession,
) -> None:
    session = clean
    from estimo_connectors import approve, generate_candidate
    from estimo_knowledge import upsert_document

    await upsert_document(
        session,
        source_type="confluence",
        source_ref="wiki://only@1",
        title="Only",
        text="Taksit içeriği.",
        acl_keys=["public"],
    )
    await session.commit()

    page = await generate_candidate(session, topic="taksit", acl_keys=["public"])
    await approve(session, page, approver="A")
    # Re-draft + re-approve the same topic.
    page = await generate_candidate(session, topic="taksit", acl_keys=["public"])
    await approve(session, page, approver="B")

    canonical = list(
        (
            await session.execute(
                select(KnowledgeChunk).where(KnowledgeChunk.source_type == "canonical")
            )
        ).scalars()
    )
    assert len(canonical) == 1  # replaced, not accumulated


async def test_canonical_approve_refuses_to_widen_past_the_source_audience(
    clean: AsyncSession,
) -> None:
    """SECURITY.md: the ACL pre-filter must never widen access. An approver naming a
    wider audience than the sources' own would publish restricted text to it."""
    session = clean
    from estimo_connectors import approve, generate_candidate
    from estimo_knowledge import upsert_document

    await upsert_document(
        session,
        source_type="confluence",
        source_ref="wiki://secret@1",
        title="Gizli",
        text="Taksitli fatura kırılımı gizli tarafı.",
        acl_keys=["confluence-group:finans"],
    )
    await session.commit()
    page = await generate_candidate(
        session, topic="taksitli fatura kırılımı", acl_keys=["confluence-group:finans"]
    )

    with pytest.raises(ValueError, match="may only narrow"):
        await approve(session, page, approver="D. Aksoy", acl_keys=["public"])

    # Disjoint audiences stay unpublishable: no reader can see every source.
    await upsert_document(
        session,
        source_type="confluence",
        source_ref="wiki://other@1",
        title="Satış",
        text="Taksitli fatura kırılımı satış tarafı.",
        acl_keys=["confluence-group:satis"],
    )
    await session.commit()
    mixed = await generate_candidate(
        session,
        topic="taksitli fatura kırılımı",
        acl_keys=["confluence-group:finans", "confluence-group:satis"],
    )
    with pytest.raises(ValueError, match="no common ACL audience"):
        await approve(session, mixed, approver="D. Aksoy")


async def test_approving_a_page_whose_sources_were_pruned_is_refused(
    clean: AsyncSession,
) -> None:
    """The body outlives its sources. Module-wiki source_refs embed the commit SHA, so
    any push prunes the previous sync's chunks — and a draft awaiting approval then has
    a body full of restricted text with no sources left to derive an audience from.
    Publishing it computed PUBLIC, which is the widening the ACL work exists to stop."""
    session = clean
    from estimo_connectors import approve, generate_candidate
    from estimo_knowledge import KnowledgeChunk, upsert_document

    await upsert_document(
        session,
        source_type="code-wiki",
        source_ref="repo://meridyen@sha1/billing",
        title="Billing",
        text="Taksitli fatura kırılımı gizli marj tablosu.",
        acl_keys=["team:meridyen"],
    )
    await session.commit()
    page = await generate_candidate(
        session, topic="taksitli fatura kırılımı", acl_keys=["team:meridyen"]
    )
    assert page.source_refs, "the draft must record what it was distilled from"

    # A commit lands; the git sync prunes every chunk from the previous SHA.
    await session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.source_type == "code-wiki"))
    await session.commit()

    with pytest.raises(ValueError, match="no longer exist"):
        await approve(session, page, approver="D. Aksoy")

    published = await session.scalar(
        select(KnowledgeChunk).where(KnowledgeChunk.source_type == "canonical")
    )
    assert published is None, "a page with vanished sources must not be published at all"


async def test_a_failing_embed_pass_leaves_the_run_succeeded(clean: AsyncSession) -> None:
    """The embed pass runs after the run's terminal state is durable. While the status
    lived only in memory, a rollback underneath reverted it to 'running' and the
    one-running-sync index wedged the connection until the hourly sweep."""
    session = clean
    from estimo_connectors.db import Connection
    from estimo_connectors.sync import run_sync

    class ExplodingGateway:
        async def embed(self, texts: list[str], *, stage: str = "embedding") -> object:
            from estimo_gateway import GatewayError

            raise GatewayError("no embedding profile configured")

    from estimo_knowledge import LedgerEntryRow

    session.add(
        LedgerEntryRow(
            brd_ref="AUR-E1",
            item_title="Embed edilecek kalem",
            item_description="metin",
        )
    )
    connection = Connection(
        kind="jira",
        name="jira-embed-fail",
        base_url="https://example.invalid",
        config={"jql": "project = AUR", "points_to_pd": 1.0},
    )
    session.add(connection)
    await session.commit()

    async def _fake_jira(*args: object, **kwargs: object) -> dict[str, object]:
        return {"issues": 0, "imported": 0}

    import estimo_connectors.sync as sync_module

    original = sync_module._sync_jira
    sync_module._sync_jira = _fake_jira
    try:
        run = await run_sync(session, connection, client=ExplodingGateway())  # type: ignore[arg-type]
    finally:
        sync_module._sync_jira = original

    assert run.status == "succeeded", "a gateway outage must not un-finish a completed crawl"
    await session.refresh(run)
    assert run.status == "succeeded", "and it must be persisted that way"
    assert run.finished_at is not None
    assert (run.stats or {}).get("embed_failed_batches") == 1, "the failure must be reported"


async def test_editing_a_page_prunes_the_superseded_version(clean: AsyncSession) -> None:
    """A Confluence source_ref embeds the page VERSION, so an edit writes a new row.
    Unpruned, the old one stays retrievable forever carrying the ACL it had THEN — so
    restricting a page at the source never takes effect for the version that was public,
    and superseded text keeps competing in search.

    Drives `_sync_confluence` itself rather than replaying its SQL: a test that issues
    the DELETE by hand passes just as happily when the lane forgets to.
    """
    session = clean
    from estimo_knowledge import KnowledgeChunk, lexical_chunk_ids

    connection = Connection(
        kind="confluence",
        name="aurora-wiki",
        base_url="https://example.invalid",
        secret_env="ESTIMO_SECRET_TEST",
        acl_keys=["public"],
        config={"email": "a@b.c", "space_keys": ["AUR"]},
    )
    session.add(connection)
    await session.commit()

    class FakeConnector:
        """Yields one page whose version and ACL change between syncs."""

        def __init__(self, version: int, acl: tuple[str, ...], body: str) -> None:
            self.version, self.acl, self.body = version, acl, body

        async def crawl(self, checkpoint: dict[str, object]) -> AsyncIterator[Any]:
            from estimo_connectors import SourceDocument

            yield SourceDocument(
                source_type="confluence",
                source_ref=f"wiki://77@{self.version}",
                title="[AUR] Taksitlendirme",
                text=self.body,
                freshness_at=None,
                authority=0.5,
                acl_keys=self.acl,
            )

        async def aclose(self) -> None:
            return None

    import estimo_connectors.sync as sync_module

    os.environ["ESTIMO_SECRET_TEST"] = "token"
    original = sync_module.ConfluenceConnector  # type: ignore[attr-defined]
    try:
        sync_module.ConfluenceConnector = lambda **kw: FakeConnector(  # type: ignore[assignment,attr-defined]
            1, ("public",), "Taksitlendirme herkese açık ilk sürüm."
        )
        run = await run_sync(session, connection)
        assert run.status == "succeeded", run.error
        assert await lexical_chunk_ids(session, "taksitlendirme", acl_keys=["public"])

        # The page is edited AND restricted at the source.
        sync_module.ConfluenceConnector = lambda **kw: FakeConnector(  # type: ignore[assignment,attr-defined]
            2, ("confluence-group:finans",), "Taksitlendirme gizli ikinci sürüm."
        )
        run = await run_sync(session, connection)
        assert run.status == "succeeded", run.error
    finally:
        sync_module.ConfluenceConnector = original  # type: ignore[attr-defined]
        os.environ.pop("ESTIMO_SECRET_TEST", None)

    refs = {row.source_ref for row in (await session.execute(select(KnowledgeChunk))).scalars()}
    assert refs == {"wiki://77@2"}, f"the superseded version survived: {refs}"
    # And a public reader can no longer reach the page at all.
    assert await lexical_chunk_ids(session, "taksitlendirme", acl_keys=["public"]) == []


def test_page_prefix_groups_every_version_of_one_page() -> None:
    from estimo_connectors.sync import _page_prefix

    assert _page_prefix("wiki://123@4") == "wiki://123@"
    assert _page_prefix("wiki://123@11") == "wiki://123@"
    # Defensive: a ref with no version must not collapse to a prefix matching siblings.
    assert _page_prefix("wiki://123") == "wiki://123"


async def test_prefix_prune_does_not_reach_across_connections(clean: AsyncSession) -> None:
    """`_` is a LIKE wildcard and the connection NAME is user-supplied (the API allows
    `[A-Za-z0-9._ -]`). Unescaped, syncing `a_b` deletes the indexed chunks of `axb`.

    Scope: this pins the PREDICATE, not the lane — it builds the prune the way
    `_sync_git` does rather than driving a real clone. It would therefore not catch the
    lane dropping `autoescape` at the call site, only the predicate being wrong. Driving
    the lane needs a git fixture per connection, which buys little here because the
    escaping is the whole behaviour under test.
    """
    session = clean
    from estimo_knowledge import KnowledgeChunk, upsert_document

    for name in ("a_b", "axb"):
        await upsert_document(
            session,
            source_type="code-wiki",
            source_ref=f"repo://{name}@sha1/billing",
            title=f"{name} billing",
            text="Modül dokümanı.",
            acl_keys=["public"],
        )
    await session.commit()

    # The shape the git lane prunes with, for connection `a_b`.
    await session.execute(
        delete(KnowledgeChunk).where(
            KnowledgeChunk.source_type == "code-wiki",
            KnowledgeChunk.source_ref.startswith("repo://a_b@", autoescape=True),
            KnowledgeChunk.source_ref.not_in(["repo://a_b@sha2/billing"]),
        )
    )
    await session.commit()

    survivors = {
        row.source_ref for row in (await session.execute(select(KnowledgeChunk))).scalars()
    }
    assert survivors == {"repo://axb@sha1/billing"}, (
        f"pruning connection a_b reached into another connection: {survivors}"
    )
