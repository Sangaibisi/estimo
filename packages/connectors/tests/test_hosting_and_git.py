"""Hosting connectors: webhook signatures, push parsing, repo listing, git sync."""

import base64
import hashlib
import hmac
import json
import subprocess
from pathlib import Path

import httpx
import pytest
import respx
from estimo_connectors import (
    clone_or_fetch,
    clone_username,
    list_repos,
    push_event_branches,
    verify_webhook,
)

SECRET = "hook-secret"
BODY = json.dumps({"push": {"changes": []}}).encode()


class TestWebhookSignatures:
    def test_bitbucket_sha256_hex(self) -> None:
        digest = hmac.new(SECRET.encode(), BODY, hashlib.sha256).hexdigest()
        assert verify_webhook("bitbucket", {"X-Hub-Signature": f"sha256={digest}"}, BODY, SECRET)
        assert not verify_webhook(
            "bitbucket", {"X-Hub-Signature": "sha256=" + "0" * 64}, BODY, SECRET
        )
        assert not verify_webhook("bitbucket", {}, BODY, SECRET)

    def test_github_sha256_header(self) -> None:
        digest = hmac.new(SECRET.encode(), BODY, hashlib.sha256).hexdigest()
        assert verify_webhook("github", {"X-Hub-Signature-256": f"sha256={digest}"}, BODY, SECRET)
        # GitHub signs into a DIFFERENT header than Bitbucket; crossing them fails.
        assert not verify_webhook("github", {"X-Hub-Signature": f"sha256={digest}"}, BODY, SECRET)

    def test_gitlab_token_and_signing_modes(self) -> None:
        assert verify_webhook("gitlab", {"X-Gitlab-Token": SECRET}, BODY, SECRET)
        assert not verify_webhook("gitlab", {"X-Gitlab-Token": "wrong"}, BODY, SECRET)
        message = b"id-1.1754200000." + BODY
        signature = base64.b64encode(
            hmac.new(SECRET.encode(), message, hashlib.sha256).digest()
        ).decode()
        headers = {
            "webhook-id": "id-1",
            "webhook-timestamp": "1754200000",
            "webhook-signature": f"v1,{signature}",
        }
        assert verify_webhook("gitlab", headers, BODY, SECRET)
        assert not verify_webhook("gitlab", {**headers, "webhook-timestamp": "999"}, BODY, SECRET)


class TestPushEvents:
    def test_bitbucket_branches(self) -> None:
        payload = {
            "push": {
                "changes": [
                    {"new": {"type": "branch", "name": "main", "target": {"hash": "abc"}}},
                    {"new": {"type": "tag", "name": "v1"}},
                    {"new": None, "old": {"type": "branch", "name": "gone"}},
                ]
            }
        }
        assert push_event_branches("bitbucket", payload) == ["main"]

    def test_github_and_gitlab_refs(self) -> None:
        assert push_event_branches("github", {"ref": "refs/heads/main"}) == ["main"]
        assert push_event_branches("gitlab", {"ref": "refs/tags/v1"}) == []


class TestCloneUsernames:
    def test_provider_specific_usernames(self) -> None:
        # Bitbucket REQUIRES the literal x-token-auth (web-verified).
        assert clone_username("bitbucket") == "x-token-auth"
        assert clone_username("github") == "x-access-token"
        assert clone_username("git") == "git"


@respx.mock
async def test_bitbucket_listing_follows_next_url() -> None:
    page1: dict[str, object] = {
        "values": [
            {
                "slug": "billing-core",
                "full_name": "aurora/billing-core",
                "mainbranch": {"name": "main"},
                "links": {
                    "clone": [
                        {"name": "https", "href": "https://bitbucket.org/aurora/billing-core.git"}
                    ]
                },
            }
        ],
        "next": "https://api.bitbucket.org/2.0/repositories/aurora?page=2",
    }
    page2: dict[str, object] = {
        "values": [
            {
                "slug": "crm-suite",
                "full_name": "aurora/crm-suite",
                "mainbranch": None,
                "links": {"clone": []},
            }
        ]
    }
    respx.get(url__startswith="https://api.bitbucket.org/2.0/repositories/aurora").mock(
        side_effect=[
            httpx.Response(200, json=page1),
            httpx.Response(200, json=page2),
        ]
    )
    repos = await list_repos("bitbucket", token="t", workspace="aurora")
    assert [repo.slug for repo in repos] == ["billing-core", "crm-suite"]
    assert repos[0].default_branch == "main"
    assert repos[0].clone_url.endswith("billing-core.git")


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    (path / "Billing.java").write_text("public class Billing {}\n")
    env_args = [
        "-c",
        "user.email=test@estimo.local",
        "-c",
        "user.name=Test",
    ]
    subprocess.run(["git", *env_args, "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", *env_args, "-C", str(path), "commit", "-q", "-m", "init"], check=True)


async def test_clone_then_fetch_local_repo(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    origin.mkdir()
    _init_repo(origin)

    dest = tmp_path / "work" / "mirror"
    state = await clone_or_fetch(f"file://{origin}", dest, branch="main")
    assert (dest / "Billing.java").exists()
    assert len(state.head_sha) == 40
    first_sha = state.head_sha

    # -a stages only TRACKED files; grow an existing one for the second commit.
    (origin / "Billing.java").write_text("public class Billing { int taksit; }\n")
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@estimo.local",
            "-c",
            "user.name=Test",
            "-C",
            str(origin),
            "commit",
            "-qam",
            "more",
        ],
        check=True,
    )
    state = await clone_or_fetch(f"file://{origin}", dest, branch="main")
    assert state.head_sha != first_sha
    assert "taksit" in (dest / "Billing.java").read_text()


async def test_clone_failure_raises_without_leaking_token(tmp_path: Path) -> None:
    from estimo_connectors import GitSyncError

    with pytest.raises(GitSyncError) as excinfo:
        await clone_or_fetch(
            f"file://{tmp_path}/does-not-exist",
            tmp_path / "dest",
            token="super-secret-token",
        )
    assert "super-secret-token" not in str(excinfo.value)
