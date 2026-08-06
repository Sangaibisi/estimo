"""Connection-level repository discovery (S14): what a configured connection sees.

The map's import flow rests on this: a platform admin configures ONE hosting
connection with a credential, and a project owner then browses the repositories it
can reach — placing them on the map without ever touching the credential.

This module is the connection-shaped entry point over `hosting.list_repos` (S9),
which speaks Bitbucket Cloud, GitHub and GitLab. What it adds:

- **Bitbucket Data Center**, the flavour the deployments this product ships to
  actually run. Cloud and DC share a brand and nothing else — different API root,
  different pagination, different auth habits — and `bitbucket.org` in the host is
  what tells them apart.
- **Coordinate derivation.** Operators paste what they have (a clone URL, a browser
  URL, a bare server); the workspace / project key / API origin are derived from it,
  with an explicit config override always winning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from estimo_connectors.base import RatePlan, paced_get
from estimo_connectors.hosting import HostedRepo, list_repos

# Bitbucket DC project keys are UPPERCASE[A-Z0-9_] in practice; personal projects
# are `~username` and usernames may carry dots/dashes. The regex is an injection
# boundary on top of URL-quoting, not a faithful grammar.
_PROJECT_KEY_RE = re.compile(r"^~?[A-Za-z][A-Za-z0-9_.\-]{0,63}$")

# Hard ceiling on how many repositories one discovery call will walk. A hosting
# project with more than this is not something the map can usefully show anyway.
MAX_REMOTE_REPOS = 500
_PAGE_SIZE = 100


class DiscoveryUnsupported(ValueError):
    """This connection kind (or hosting flavour) has no discovery implementation."""


@dataclass(frozen=True)
class BitbucketCoordinates:
    server: str  # scheme://host[/context]
    project_key: str


def _origin(base_url: str) -> tuple[str, list[str]]:
    parsed = urlsplit(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"not an http(s) URL: {base_url!r}")
    return f"{parsed.scheme}://{parsed.netloc}", [s for s in parsed.path.split("/") if s]


def bitbucket_coordinates(base_url: str, config: dict[str, Any]) -> BitbucketCoordinates:
    """Derive (server, project key) from whatever URL the connection was set up with.

    Operators paste what they have: a clone URL (`…/scm/TTG/backend.git`), a browser
    URL (`…/projects/TTG/repos/backend`), or just the server. All three carry the
    context path (Bitbucket DC is routinely mounted under one), so the split keys on
    the `/scm/` and `/projects/` markers instead of assuming the origin is the
    server. An explicit `config["project_key"]` always wins over the derived key.
    """
    origin, segments = _origin(base_url)
    context: list[str] = segments
    derived_key: str | None = None
    for marker in ("scm", "projects"):
        if marker in segments:
            index = segments.index(marker)
            context = segments[:index]
            if len(segments) > index + 1:
                derived_key = segments[index + 1]
            break

    override = config.get("project_key")
    key = str(override) if override else derived_key
    if not key:
        raise ValueError(
            "cannot tell which Bitbucket project this connection points at — "
            'use a …/scm/<PROJECT>/… URL or set config {"project_key": "…"}'
        )
    if not _PROJECT_KEY_RE.match(key):
        raise ValueError(f"implausible Bitbucket project key: {key!r}")

    server = origin
    if context:
        server += "/" + "/".join(quote(segment, safe="") for segment in context)
    return BitbucketCoordinates(server=server, project_key=key)


def _clone_url(value: dict[str, Any]) -> str | None:
    for link in (value.get("links") or {}).get("clone") or []:
        if link.get("name") in ("http", "https") and link.get("href"):
            return str(link["href"])
    return None


async def _bitbucket_dc_repos(
    coordinates: BitbucketCoordinates,
    *,
    token: str,
    username: str | None,
    bearer: bool,
) -> list[HostedRepo]:
    """Walk `/rest/api/1.0/projects/{key}/repos` (start/limit pages, isLastPage).

    The credential travels exactly the way the git sync sends it: a DC personal
    access token as `Authorization: Bearer` (they are rejected as Basic passwords —
    the S13 lesson), anything else as Basic with the configured username.
    """
    headers = {"Accept": "application/json"}
    auth: tuple[str, str] | None = None
    if bearer:
        headers["Authorization"] = f"Bearer {token}"
    else:
        auth = (username or "", token)

    repos: list[HostedRepo] = []
    plan = RatePlan(min_interval=0.1)
    url = (
        f"{coordinates.server}/rest/api/1.0/projects/"
        f"{quote(coordinates.project_key, safe='~')}/repos"
    )
    start = 0
    async with httpx.AsyncClient(timeout=20.0, headers=headers, auth=auth) as client:
        while len(repos) < MAX_REMOTE_REPOS:
            try:
                response = await paced_get(
                    client, url, params={"limit": _PAGE_SIZE, "start": start}, plan=plan
                )
            except httpx.HTTPStatusError as exc:
                # paced_get raises for any non-2xx; translate the ones an operator
                # can act on into sentences (and never echo the credential).
                code = exc.response.status_code
                if code in (401, 403):
                    raise ValueError(
                        f"Bitbucket refused the connection's credential ({code}) — "
                        "check the token and its project permission"
                    ) from exc
                if code == 404:
                    raise ValueError(
                        f"Bitbucket project {coordinates.project_key!r} was not found "
                        f"on {coordinates.server}"
                    ) from exc
                raise
            payload = response.json()
            for value in payload.get("values") or []:
                slug = str(value.get("slug") or "").strip()
                if not slug:
                    continue
                repos.append(
                    HostedRepo(
                        slug=slug,
                        full_name=f"{coordinates.project_key}/{slug}",
                        clone_url=_clone_url(value) or "",
                        default_branch=None,
                    )
                )
            if payload.get("isLastPage", True):
                break
            start = int(payload.get("nextPageStart") or (start + _PAGE_SIZE))
    return repos


async def remote_repos(
    *,
    kind: str,
    base_url: str,
    config: dict[str, Any],
    token: str | None,
    username: str | None = None,
    bearer: bool = False,
) -> tuple[str, list[HostedRepo]]:
    """(human-readable scope, repositories) the connection's credential can see."""
    if kind not in ("bitbucket", "github", "gitlab"):
        raise DiscoveryUnsupported(
            f"repository discovery is not implemented for {kind!r} connections — "
            "add repositories to the map by name instead"
        )
    if not token:
        raise ValueError("this connection has no credential to browse with")

    origin, segments = _origin(base_url)
    host = urlsplit(origin).hostname or ""

    if kind == "bitbucket":
        if host == "bitbucket.org":
            workspace = str(config.get("workspace") or (segments[0] if segments else ""))
            if not workspace:
                raise ValueError(
                    'cannot tell the Bitbucket Cloud workspace — set config {"workspace": "…"}'
                )
            repos = await list_repos("bitbucket", token=token, workspace=workspace)
            return f"bitbucket.org/{workspace}", repos
        coordinates = bitbucket_coordinates(base_url, config)
        repos = await _bitbucket_dc_repos(
            coordinates, token=token, username=username, bearer=bearer
        )
        return f"{coordinates.server} · {coordinates.project_key}", repos

    if kind == "github":
        # A clone URL is github.com/{org}/{repo}.git; a bare org URL has one segment.
        org = str(config.get("workspace") or (segments[0] if segments else "")) or None
        repos = await list_repos("github", token=token, workspace=org)
        return f"github.com/{org}" if org else "your repositories", repos

    # gitlab: the API root is the origin (self-hosted instances included).
    repos = await list_repos("gitlab", token=token, base_url=origin)
    return origin, repos
