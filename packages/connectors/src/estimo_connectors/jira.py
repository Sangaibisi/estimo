"""Optional Jira connector (S9-6): read-only epic/story pull that can feed the ledger.

Web-verified facts (2026) this module encodes: the classic `/rest/api/3/search` is
REMOVED (410) — the only supported JQL search is `/rest/api/3/search/jql`, paginated
by an opaque `nextPageToken` (no totals; no page math), returning only ids unless
`fields` is explicit. Story points has no stable field id: it is discovered per site
via `/rest/api/3/field` by name ("Story Points" company-managed / "Story point
estimate" team-managed — both may exist). Auth: same Basic email+API-token pair as
Confluence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from estimo_connectors.base import RatePlan, paced_get

STORY_POINT_FIELD_NAMES = {"story points", "story point estimate"}


@dataclass(frozen=True)
class JiraIssue:
    key: str
    issue_type: str
    summary: str
    description: str | None
    status: str | None
    parent_key: str | None
    story_points: float | None


class JiraConnector:
    def __init__(
        self,
        *,
        base_url: str,
        email: str,
        api_token: str,
        plan: RatePlan | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.plan = plan or RatePlan(min_interval=0.2)
        self._client = client or httpx.AsyncClient(
            base_url=self.base_url, auth=(email, api_token), timeout=30.0
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def story_point_field_ids(self) -> list[str]:
        """Per-site discovery — never hardcode customfield_10016."""
        fields = (await paced_get(self._client, "/rest/api/3/field", plan=self.plan)).json()
        return [
            field["id"]
            for field in fields
            if (field.get("name") or "").lower() in STORY_POINT_FIELD_NAMES
            and (field.get("schema") or {}).get("type") == "number"
        ]

    async def pull_issues(self, *, jql: str, limit: int = 500) -> list[JiraIssue]:
        point_fields = await self.story_point_field_ids()
        fields = ["summary", "description", "issuetype", "status", "parent", *point_fields]
        issues: list[JiraIssue] = []
        token: str | None = None
        while len(issues) < limit:
            params: dict[str, Any] = {
                "jql": jql,
                "maxResults": min(100, limit - len(issues)),
                "fields": ",".join(fields),
            }
            if token:
                params["nextPageToken"] = token
            payload = (
                await paced_get(
                    self._client, "/rest/api/3/search/jql", plan=self.plan, params=params
                )
            ).json()
            for item in payload.get("issues", []):
                issues.append(_issue(item, point_fields))
            token = payload.get("nextPageToken")
            if not token or payload.get("isLast"):
                break
        return issues


def _issue(item: dict[str, Any], point_fields: list[str]) -> JiraIssue:
    fields = item.get("fields", {})
    points = next((fields[field] for field in point_fields if fields.get(field) is not None), None)
    description = fields.get("description")
    if isinstance(description, dict):
        description = _adf_text(description)
    return JiraIssue(
        key=item.get("key", ""),
        issue_type=(fields.get("issuetype") or {}).get("name", ""),
        summary=fields.get("summary", ""),
        description=description,
        status=(fields.get("status") or {}).get("name"),
        parent_key=(fields.get("parent") or {}).get("key"),
        story_points=float(points) if points is not None else None,
    )


def _adf_text(node: dict[str, Any]) -> str:
    """Flatten Atlassian Document Format to plain text."""
    parts: list[str] = []
    if node.get("type") == "text":
        parts.append(node.get("text", ""))
    for child in node.get("content", []) or []:
        parts.append(_adf_text(child))
    joined = " ".join(part for part in parts if part)
    return joined if node.get("type") != "paragraph" else joined + "\n"
