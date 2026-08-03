"""Regression tests for the S9 adversarial-review findings."""

import base64
import hashlib
import hmac

import httpx
import pytest
import respx

from estimo_connectors import ConfluenceConnector, RatePlan, storage_to_text, verify_webhook

BASE = "https://aurora.atlassian.net"


def _connector(**kwargs: object) -> ConfluenceConnector:
    defaults: dict[str, object] = {
        "base_url": BASE,
        "email": "svc@aurora.example",
        "api_token": "token",
        "space_keys": ("AUR",),
        "default_acl": ("space:AUR",),
        "plan": RatePlan(min_interval=0.0),
    }
    defaults.update(kwargs)
    return ConfluenceConnector(**defaults)  # type: ignore[arg-type]


def test_confluence_requires_scoped_space_keys() -> None:
    # ACL widening finding: an unscoped crawl is refused outright.
    with pytest.raises(ValueError, match="space_keys"):
        _connector(space_keys=())
    with pytest.raises(ValueError, match="invalid confluence space key"):
        _connector(space_keys=("AUR OR 1=1",))


def test_storage_to_text_preserves_cdata_macro_body() -> None:
    html = (
        "<p>intro</p>"
        '<ac:structured-macro ac:name="code"><ac:plain-text-body>'
        "<![CDATA[SELECT taksit FROM fatura;]]>"
        "</ac:plain-text-body></ac:structured-macro>"
    )
    text = storage_to_text(html)
    assert "SELECT taksit FROM fatura;" in text


@pytest.mark.asyncio
@respx.mock
async def test_pagination_follows_next_verbatim_no_double_encoding() -> None:
    # Cursor double-encoding finding: the connector must follow _links.next as-is.
    # The cursor carries base64 padding (%3D%3D); a re-encoding step would emit
    # %253D%253D and this exact-match route would never be hit.
    next_url = f"{BASE}/wiki/api/v2/spaces?cursor=eyJpZCI6IjEifQ%3D%3D&limit=100"
    route = respx.route(method="GET", url__startswith=f"{BASE}/wiki/api/v2/spaces")

    def handler(request: httpx.Request) -> httpx.Response:
        if "cursor=" in str(request.url):
            # Reached only if the cursor survived unmangled.
            assert "%253D" not in str(request.url), "cursor was double-encoded"
            return httpx.Response(
                200, json={"results": [{"id": "s2", "key": "AUR2"}], "_links": {}}
            )
        return httpx.Response(
            200, json={"results": [{"id": "s1", "key": "AUR"}], "_links": {"next": next_url}}
        )

    route.side_effect = handler
    connector = _connector(space_keys=("AUR", "AUR2"))
    spaces = await connector._spaces()
    await connector.aclose()
    assert [s["id"] for s in spaces] == ["s1", "s2"]


@pytest.mark.asyncio
@respx.mock
async def test_pagination_loop_guard() -> None:
    loop_url = f"{BASE}/wiki/api/v2/spaces?cursor=stuck"
    respx.route(method="GET", url__startswith=f"{BASE}/wiki/api/v2/spaces").respond(
        json={"results": [{"id": "s1"}], "_links": {"next": loop_url}}
    )
    connector = _connector()
    with pytest.raises(RuntimeError, match="pagination loop"):
        await connector._spaces()
    await connector.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_effective_acl_walks_ancestors_for_inherited_restriction() -> None:
    # ACL inheritance finding: a child of a restricted parent inherits the parent's
    # principals, not the connection default.
    def unrestricted() -> dict[str, object]:
        return {
            "results": [
                {
                    "operation": "read",
                    "restrictions": {"user": {"results": []}, "group": {"results": []}},
                }
            ]
        }

    respx.get(f"{BASE}/wiki/rest/api/content/child/restriction").respond(json=unrestricted())
    respx.get(f"{BASE}/wiki/rest/api/content/parent/restriction").respond(
        json={
            "results": [
                {
                    "operation": "read",
                    "restrictions": {
                        "user": {"results": [{"accountId": "acc-1"}]},
                        "group": {"results": []},
                    },
                }
            ]
        }
    )
    connector = _connector()
    acl = await connector._effective_acl("child", "parent")
    await connector.aclose()
    assert acl == ("confluence-user:acc-1",)


class TestWebhookReplay:
    def test_gitlab_signed_delivery_expires(self) -> None:
        secret = "s"
        body = b"{}"
        message = b"id-1.1000000000." + body
        signature = base64.b64encode(
            hmac.new(secret.encode(), message, hashlib.sha256).digest()
        ).decode()
        headers = {
            "webhook-id": "id-1",
            "webhook-timestamp": "1000000000",
            "webhook-signature": f"v1,{signature}",
        }
        # Fresh (now == delivery time) passes; a replay 10 minutes later fails.
        assert verify_webhook("gitlab", headers, body, secret, now=1000000000.0)
        assert not verify_webhook("gitlab", headers, body, secret, now=1000000600.0)


def test_rate_plan_recovers_after_nearlimit() -> None:
    plan = RatePlan(min_interval=0.5)
    plan.observe_budget(httpx.Response(200, headers={"X-RateLimit-NearLimit": "true"}))
    assert plan.min_interval == 1.0  # slowed
    plan.observe_budget(httpx.Response(200))
    assert plan.min_interval == 0.5  # recovered to base, not stuck
