"""End-to-end sync orchestration over a local git repo (S9-2 → S5 chain)."""

import subprocess
from pathlib import Path

import pytest
from estimo_connectors import Connection, SyncRun, run_sync
from estimo_connectors.graphstore import load_code_graphs
from estimo_knowledge import KnowledgeChunk
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.db

REPO_ROOT = Path(__file__).resolve().parents[3]
MINI_REPO = REPO_ROOT / "fixtures" / "repo" / "meridyen-mini"


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@estimo.local",
            "-c",
            "user.name=Test",
            "-C",
            str(cwd),
            *args,
        ],
        check=True,
        capture_output=True,
    )


@pytest.fixture
async def clean_connector_tables(session: AsyncSession, clean_tables: None) -> AsyncSession:
    await session.execute(text("TRUNCATE connections, sync_runs CASCADE"))
    await session.commit()
    return session


async def test_git_sync_indexes_repo_with_connection_acl(
    clean_connector_tables: AsyncSession, tmp_path: Path
) -> None:
    session = clean_connector_tables
    origin = tmp_path / "origin"
    origin.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(origin)], check=True)
    for path in MINI_REPO.rglob("*"):
        if path.is_file():
            target = origin / path.relative_to(MINI_REPO)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
    _git("add", ".", cwd=origin)
    _git("commit", "-q", "-m", "meridyen import", cwd=origin)

    connection = Connection(
        kind="git",
        name="meridyen-mini",
        base_url=f"file://{origin}",
        config={"branch": "main"},
        acl_keys=["team:meridyen"],
    )
    session.add(connection)
    await session.commit()

    run = await run_sync(session, connection, repos_dir=tmp_path / "work")
    assert run.status == "succeeded", run.error
    assert run.stats is not None and run.stats["modules"] >= 3
    assert run.checkpoint is not None and len(run.checkpoint["head_sha"]) == 40

    # S13-2: the graph the wiki generation used is persisted, keyed on the
    # connection, at the synced commit — and its derived maps rebuild on load.
    graphs = await load_code_graphs(session)
    assert [g.repo for g in graphs] == ["meridyen-mini"]
    assert graphs[0].commit == run.checkpoint["head_sha"]
    assert graphs[0].symbol_terms
    assert run.stats["graph"]["files"] == len(graphs[0].files)

    chunks = list(
        (
            await session.execute(
                select(KnowledgeChunk).where(KnowledgeChunk.source_type == "code-wiki")
            )
        ).scalars()
    )
    assert chunks
    # Connection ACL is stamped on every ingested chunk; freshness is the COMMIT
    # time, not ingestion time.
    assert all(chunk.acl_keys == ["team:meridyen"] for chunk in chunks)
    assert all(chunk.freshness_at is not None for chunk in chunks)

    # A second sync resumes cleanly (idempotent fetch path) and records a new run.
    second = await run_sync(session, connection, repos_dir=tmp_path / "work")
    assert second.status == "succeeded", second.error
    runs = list((await session.execute(select(SyncRun))).scalars())
    assert len(runs) == 2
    # The graph row is replaced in place, never accumulated per commit.
    assert len(await load_code_graphs(session)) == 1


async def test_failed_sync_records_error(
    clean_connector_tables: AsyncSession, tmp_path: Path
) -> None:
    session = clean_connector_tables
    connection = Connection(
        kind="git",
        name="broken",
        base_url=f"file://{tmp_path}/missing",
        config={},
    )
    session.add(connection)
    await session.commit()

    run = await run_sync(session, connection, repos_dir=tmp_path / "work")
    assert run.status == "failed"
    assert run.error
