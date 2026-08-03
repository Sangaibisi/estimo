"""DB-backed regression tests for the S9 review findings on sync orchestration."""

import subprocess
import uuid
from pathlib import Path

import pytest
from estimo_connectors import Connection, SyncRun, run_sync
from estimo_connectors.sync import _last_checkpoint, _workdir_name, sweep_interrupted_runs
from estimo_knowledge import KnowledgeChunk
from sqlalchemy import select, text
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
    # Sources share no common audience → publishing would widen; must be refused.
    with pytest.raises(ValueError, match="common ACL audience"):
        await approve(session, page, approver="D. Aksoy")

    # With an explicit narrower audience it publishes to exactly that key.
    approved = await approve(
        session, page, approver="D. Aksoy", acl_keys=["confluence-group:finans"]
    )
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
