"""S14: repository discovery through a configured connection.

Two halves. Coordinate derivation is pure logic — operators paste clone URLs,
browser URLs and bare servers, and all must resolve to the same (server, project).
The walker half runs against a respx-faked Bitbucket Data Center: paging follows
`isLastPage`/`nextPageStart`, the credential travels exactly as the git sync sends
it, and refusals become sentences instead of tracebacks.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from estimo_connectors.discovery import (
    DiscoveryUnsupported,
    bitbucket_coordinates,
    remote_repos,
)

SERVER = "https://bitbucket.dc.invalid"


class TestBitbucketCoordinates:
    def test_the_three_url_shapes_operators_actually_paste(self) -> None:
        for url in (
            f"{SERVER}/scm/TTG/backend.git",
            f"{SERVER}/projects/TTG/repos/backend/browse",
            f"{SERVER}/projects/TTG",
        ):
            coordinates = bitbucket_coordinates(url, {})
            assert (coordinates.server, coordinates.project_key) == (SERVER, "TTG")

    def test_a_context_path_stays_part_of_the_server(self) -> None:
        coordinates = bitbucket_coordinates(f"{SERVER}/stash/scm/TTG/backend.git", {})
        assert coordinates.server == f"{SERVER}/stash"
        assert coordinates.project_key == "TTG"

    def test_an_explicit_project_key_wins_over_the_derived_one(self) -> None:
        coordinates = bitbucket_coordinates(
            f"{SERVER}/scm/TTG/backend.git", {"project_key": "OTHER"}
        )
        assert coordinates.project_key == "OTHER"

    def test_personal_project_keys_are_legal(self) -> None:
        coordinates = bitbucket_coordinates(f"{SERVER}/scm/~emrullah.yildirim/tool.git", {})
        assert coordinates.project_key == "~emrullah.yildirim"

    def test_underivable_and_implausible_keys_are_refused(self) -> None:
        with pytest.raises(ValueError, match="cannot tell which Bitbucket project"):
            bitbucket_coordinates(SERVER, {})
        with pytest.raises(ValueError, match="implausible"):
            bitbucket_coordinates(SERVER, {"project_key": "a/../b"})
        with pytest.raises(ValueError, match="http"):
            bitbucket_coordinates("ssh://git@host/TTG/x.git", {})


def _page(
    values: list[dict[str, Any]], *, last: bool, next_start: int | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {"values": values, "isLastPage": last}
    if next_start is not None:
        payload["nextPageStart"] = next_start
    return payload


def _repo(slug: str) -> dict[str, Any]:
    return {
        "slug": slug,
        "name": slug,
        "links": {
            "clone": [
                {"name": "ssh", "href": f"ssh://git@host/TTG/{slug}.git"},
                {"name": "http", "href": f"{SERVER}/scm/TTG/{slug}.git"},
            ]
        },
    }


@respx.mock
async def test_dc_walker_pages_and_sends_the_bearer_exactly_like_the_git_sync() -> None:
    route = respx.get(f"{SERVER}/rest/api/1.0/projects/TTG/repos").mock(
        side_effect=[
            httpx.Response(200, json=_page([_repo("backend")], last=False, next_start=1)),
            httpx.Response(200, json=_page([_repo("frontend")], last=True)),
        ]
    )
    scope, repos = await remote_repos(
        kind="bitbucket",
        base_url=f"{SERVER}/scm/TTG/backend.git",
        config={"auth": "bearer"},
        token="pat-token",
        bearer=True,
    )
    assert scope == f"{SERVER} · TTG"
    assert [repo.slug for repo in repos] == ["backend", "frontend"]
    # The http clone link is chosen (the ssh one cannot carry the PAT).
    assert repos[0].clone_url == f"{SERVER}/scm/TTG/backend.git"
    first, second = route.calls
    assert first.request.headers["Authorization"] == "Bearer pat-token"
    assert first.request.url.params["start"] == "0"
    assert second.request.url.params["start"] == "1"


@respx.mock
async def test_refusals_become_sentences_without_the_credential() -> None:
    respx.get(f"{SERVER}/rest/api/1.0/projects/TTG/repos").mock(
        return_value=httpx.Response(403, json={})
    )
    with pytest.raises(ValueError, match="refused the connection's credential"):
        await remote_repos(
            kind="bitbucket",
            base_url=f"{SERVER}/scm/TTG/x.git",
            config={},
            token="pat",
            bearer=True,
        )


async def test_kinds_without_discovery_say_so() -> None:
    with pytest.raises(DiscoveryUnsupported, match="not implemented"):
        await remote_repos(kind="git", base_url="https://host/x.git", config={}, token="t")
    with pytest.raises(ValueError, match="no credential"):
        await remote_repos(
            kind="bitbucket", base_url=f"{SERVER}/scm/TTG/x.git", config={}, token=None
        )
