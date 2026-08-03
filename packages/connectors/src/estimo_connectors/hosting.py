"""Git hosting connectors (S9-2): Bitbucket FIRST-CLASS, GitHub/GitLab equivalents.

Web-verified facts (2026) this module encodes:
- Bitbucket Cloud app passwords were REMOVED 2026-07-28 — auth is a workspace/repo
  Access Token (`Authorization: Bearer …`); repo listing follows the absolute
  `next` URL (never page math); webhooks carry a top-level `secret` and deliveries
  are signed `X-Hub-Signature: sha256=<hex>` (HMAC-SHA256 over the RAW body).
- GitHub: fine-grained PAT; `X-Hub-Signature-256: sha256=<hex>`.
- GitLab: project access token (`PRIVATE-TOKEN`); legacy `X-Gitlab-Token` plain
  compare, plus the GitLab 19.0 `webhook-signature` (`v1,<base64>` HMAC-SHA256 over
  `{id}.{timestamp}.{body}`).
- Clone usernames: Bitbucket requires the literal `x-token-auth`; GitHub accepts
  `x-access-token`; GitLab accepts any username with a project token.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

import httpx

from estimo_connectors.base import RatePlan, paced_get


@dataclass(frozen=True)
class HostedRepo:
    slug: str
    full_name: str
    clone_url: str
    default_branch: str | None


def clone_username(kind: str) -> str:
    return {"bitbucket": "x-token-auth", "github": "x-access-token", "gitlab": "oauth2"}.get(
        kind, "git"
    )


async def list_repos(
    kind: str,
    *,
    token: str,
    workspace: str | None = None,
    base_url: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[HostedRepo]:
    """List repositories the credential can see (Admin → Connections picker)."""
    plan = RatePlan(min_interval=0.1)
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=30.0)
    try:
        if kind == "bitbucket":
            return await _bitbucket_repos(client, plan, token=token, workspace=workspace)
        if kind == "github":
            return await _github_repos(client, plan, token=token, org=workspace)
        if kind == "gitlab":
            return await _gitlab_repos(
                client, plan, token=token, base_url=base_url or "https://gitlab.com"
            )
        raise ValueError(f"unsupported hosting kind: {kind}")
    finally:
        if owns_client:
            await client.aclose()


async def _bitbucket_repos(
    client: httpx.AsyncClient, plan: RatePlan, *, token: str, workspace: str | None
) -> list[HostedRepo]:
    if not workspace:
        raise ValueError("bitbucket listing requires a workspace slug")
    client.headers["Authorization"] = f"Bearer {token}"
    url = f"https://api.bitbucket.org/2.0/repositories/{workspace}?pagelen=100&sort=-updated_on"
    repos: list[HostedRepo] = []
    while url:
        payload = (await paced_get(client, url, plan=plan)).json()
        for repo in payload.get("values", []):
            https_clone = next(
                (
                    link["href"]
                    for link in repo.get("links", {}).get("clone", [])
                    if link.get("name") == "https"
                ),
                None,
            )
            repos.append(
                HostedRepo(
                    slug=repo["slug"],
                    full_name=repo["full_name"],
                    clone_url=https_clone or "",
                    default_branch=(repo.get("mainbranch") or {}).get("name"),
                )
            )
        url = payload.get("next")  # absolute URL per the API contract
    return repos


async def _github_repos(
    client: httpx.AsyncClient, plan: RatePlan, *, token: str, org: str | None
) -> list[HostedRepo]:
    client.headers["Authorization"] = f"Bearer {token}"
    client.headers["Accept"] = "application/vnd.github+json"
    url: str | None = (
        f"https://api.github.com/orgs/{org}/repos?per_page=100"
        if org
        else "https://api.github.com/user/repos?per_page=100"
    )
    repos: list[HostedRepo] = []
    while url:
        response = await paced_get(client, url, plan=plan)
        for repo in response.json():
            repos.append(
                HostedRepo(
                    slug=repo["name"],
                    full_name=repo["full_name"],
                    clone_url=repo["clone_url"],
                    default_branch=repo.get("default_branch"),
                )
            )
        url = response.links.get("next", {}).get("url")
    return repos


async def _gitlab_repos(
    client: httpx.AsyncClient, plan: RatePlan, *, token: str, base_url: str
) -> list[HostedRepo]:
    client.headers["PRIVATE-TOKEN"] = token
    url: str | None = f"{base_url.rstrip('/')}/api/v4/projects?membership=true&per_page=100"
    repos: list[HostedRepo] = []
    while url:
        response = await paced_get(client, url, plan=plan)
        for repo in response.json():
            repos.append(
                HostedRepo(
                    slug=repo["path"],
                    full_name=repo["path_with_namespace"],
                    clone_url=repo["http_url_to_repo"],
                    default_branch=repo.get("default_branch"),
                )
            )
        url = response.links.get("next", {}).get("url")
    return repos


def verify_webhook(kind: str, headers: dict[str, str], body: bytes, secret: str) -> bool:
    """Constant-time verification of a push-webhook delivery against the RAW bytes."""
    lowered = {key.lower(): value for key, value in headers.items()}
    if kind == "bitbucket":
        return _verify_hub_signature(lowered.get("x-hub-signature", ""), body, secret)
    if kind == "github":
        return _verify_hub_signature(lowered.get("x-hub-signature-256", ""), body, secret)
    if kind == "gitlab":
        signature = lowered.get("webhook-signature")
        if signature:
            webhook_id = lowered.get("webhook-id", "")
            timestamp = lowered.get("webhook-timestamp", "")
            message = f"{webhook_id}.{timestamp}.".encode() + body
            expected = base64.b64encode(
                hmac.new(secret.encode(), message, hashlib.sha256).digest()
            ).decode()
            provided = signature.removeprefix("v1,")
            return hmac.compare_digest(provided, expected)
        return hmac.compare_digest(lowered.get("x-gitlab-token", ""), secret)
    return False


def _verify_hub_signature(header: str, body: bytes, secret: str) -> bool:
    if not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header.removeprefix("sha256="), expected)


def push_event_branches(kind: str, payload: dict[str, Any]) -> list[str]:
    """Branch names touched by a push delivery (for incremental re-index decisions)."""
    if kind == "bitbucket":
        return [
            change["new"]["name"]
            for change in payload.get("push", {}).get("changes", [])
            if change.get("new") and change["new"].get("type") == "branch"
        ]
    if kind == "github":
        ref = payload.get("ref", "")
        return [ref.removeprefix("refs/heads/")] if ref.startswith("refs/heads/") else []
    if kind == "gitlab":
        ref = payload.get("ref", "")
        return [ref.removeprefix("refs/heads/")] if ref.startswith("refs/heads/") else []
    return []
