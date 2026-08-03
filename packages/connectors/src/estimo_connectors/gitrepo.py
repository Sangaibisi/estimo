"""Git repository sync (S9-2) — clone/fetch via the git binary, index via the S5 chain.

Engineering choice (web-verified): the system git client over pure-Python
implementations — Poetry's own fallback behavior validates that credential and
transport edge cases still need the real client; the slim image installs `git`.

Credentials NEVER touch argv, remote URLs, or `.git/config`: an ephemeral
`GIT_ASKPASS` script reads them from environment variables that exist only for the
child process. Shallow, single-branch clones keep first syncs fast.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("estimo.connectors.git")

_ASKPASS = """#!/bin/sh
case "$1" in
  Username*) printf '%s' "$ESTIMO_GIT_USERNAME" ;;
  Password*) printf '%s' "$ESTIMO_GIT_PASSWORD" ;;
esac
"""


@dataclass(frozen=True)
class RepoState:
    path: Path
    head_sha: str
    head_committed_at: dt.datetime


class GitSyncError(RuntimeError):
    pass


async def _run_git(
    args: list[str],
    *,
    cwd: Path | None = None,
    username: str | None = None,
    token: str | None = None,
) -> str:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"ESTIMO_GIT_USERNAME", "ESTIMO_GIT_PASSWORD", "GIT_ASKPASS"}
    }
    env["GIT_TERMINAL_PROMPT"] = "0"
    askpass_path: str | None = None
    if token is not None:
        with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as handle:
            handle.write(_ASKPASS)
            askpass_path = handle.name
        os.chmod(askpass_path, stat.S_IRWXU)
        env["GIT_ASKPASS"] = askpass_path
        env["ESTIMO_GIT_USERNAME"] = username or "x-token-auth"
        env["ESTIMO_GIT_PASSWORD"] = token
    try:
        process = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            # stderr may echo the URL but never the credential (ASKPASS keeps it out).
            raise GitSyncError(stderr.decode(errors="replace").strip()[:500])
        return stdout.decode(errors="replace")
    finally:
        if askpass_path:
            os.unlink(askpass_path)


async def clone_or_fetch(
    url: str,
    dest: Path,
    *,
    branch: str | None = None,
    username: str | None = None,
    token: str | None = None,
    depth: int = 1,
) -> RepoState:
    """Idempotent sync of one repo working tree; returns the synced HEAD state."""
    if (dest / ".git").exists():
        await _run_git(
            ["fetch", "--depth", str(depth), "origin", *([branch] if branch else ["HEAD"])],
            cwd=dest,
            username=username,
            token=token,
        )
        # Always reset to FETCH_HEAD: after a --single-branch clone the fetch
        # refspec does not track OTHER branches, so origin/<new-branch> never
        # materialises when the configured branch changes — FETCH_HEAD does.
        await _run_git(["reset", "--hard", "FETCH_HEAD"], cwd=dest)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        args = ["clone", "--depth", str(depth), "--single-branch"]
        if branch:
            args += ["--branch", branch]
        args += [url, str(dest)]
        await _run_git(args, username=username, token=token)

    head_sha = (await _run_git(["rev-parse", "HEAD"], cwd=dest)).strip()
    committed = (await _run_git(["show", "-s", "--format=%cI", "HEAD"], cwd=dest)).strip()
    return RepoState(
        path=dest,
        head_sha=head_sha,
        head_committed_at=dt.datetime.fromisoformat(committed),
    )
