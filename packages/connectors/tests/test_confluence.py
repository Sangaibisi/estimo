"""Confluence crawler: pagination, ACL mapping, checkpoints, rate-limit obedience."""

import httpx
import pytest
import respx
from estimo_connectors import ConfluenceConnector, RatePlan, storage_to_text

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


def _page_payload(page_id: str, title: str, *, version: int = 3) -> dict[str, object]:
    return {
        "id": page_id,
        "title": title,
        "version": {"number": version, "createdAt": "2026-07-01T10:00:00Z"},
        "body": {
            "storage": {
                "value": (
                    "<h1>Kurulum</h1><p>Taksitli fatura kırılımı billing-core "
                    "üzerinde çalışır.</p><p>&amp; makrolar metnini korur.</p>"
                )
            }
        },
    }


def _no_restrictions() -> dict[str, object]:
    return {
        "results": [
            {
                "operation": "read",
                "restrictions": {
                    "user": {"results": []},
                    "group": {"results": []},
                },
            }
        ]
    }


class TestStorageToText:
    def test_code_macro_keeps_comparison_operators(self) -> None:
        """CDATA was inlined BEFORE the tag pass, so everything between a `<` and the
        next `>` inside a code sample was deleted: `if (tutar < 100 AND adet > 2)`
        arrived as `if (tutar 2)`. In a telco BSS wiki that is where the rules live."""
        rule = "if (tutar < 100 AND adet > 2) { indirim(); }"
        text = storage_to_text(
            "<p>Kural:</p><ac:structured-macro ac:name='code'><ac:plain-text-body>"
            f"<![CDATA[{rule}]]></ac:plain-text-body></ac:structured-macro>"
        )
        assert rule in text, f"the tag-stripper ate part of the code sample: {text!r}"

    def test_code_macro_text_is_not_entity_unescaped(self) -> None:
        """A code sample's `&amp;` is literal source, not an entity to resolve."""
        text = storage_to_text("<ac:plain-text-body><![CDATA[a &amp; b]]></ac:plain-text-body>")
        assert "a &amp; b" in text

    def test_table_row_keeps_its_cells_together(self) -> None:
        """Confluence wraps cell content in <p>, so the generic block pass put every
        cell on its own line and a field table lost the field-to-type association —
        `musteri_no` and `VARCHAR(20)` unsearchable as a pair, and meaningless to read."""
        text = storage_to_text(
            "<table><tbody>"
            "<tr><th><p>Alan</p></th><th><p>Tip</p></th></tr>"
            "<tr><td><p>musteri_no</p></td><td><p>VARCHAR(20)</p></td></tr>"
            "</tbody></table>"
        )
        rows = text.splitlines()
        assert rows == ["Alan · Tip", "musteri_no · VARCHAR(20)"], rows

    def test_strips_markup_and_unescapes(self) -> None:
        text = storage_to_text("<h1>Başlık</h1><p>a &amp; b</p><br/><ul><li>madde</li></ul>")
        assert "Başlık" in text and "a & b" in text and "madde" in text
        assert "<" not in text


@pytest.mark.asyncio
@respx.mock
async def test_full_crawl_maps_acl_and_checkpoints() -> None:
    respx.get(f"{BASE}/wiki/api/v2/spaces").respond(
        json={"results": [{"id": "s1", "key": "AUR"}], "_links": {}}
    )
    respx.get(f"{BASE}/wiki/api/v2/spaces/s1/pages").respond(
        json={
            "results": [
                {"id": "p1", "version": {"createdAt": "2026-07-01T10:00:00Z"}},
                {"id": "p2", "version": {"createdAt": "2026-06-01T10:00:00Z"}},
            ],
            "_links": {},
        }
    )
    respx.get(f"{BASE}/wiki/api/v2/pages/p1").respond(json=_page_payload("p1", "Kurulum"))
    respx.get(f"{BASE}/wiki/api/v2/pages/p2").respond(json=_page_payload("p2", "Gizli"))
    respx.get(f"{BASE}/wiki/rest/api/content/p1/restriction").respond(json=_no_restrictions())
    respx.get(f"{BASE}/wiki/rest/api/content/p2/restriction").respond(
        json={
            "results": [
                {
                    "operation": "read",
                    "restrictions": {
                        "user": {"results": [{"accountId": "acc-1"}]},
                        "group": {"results": [{"id": "g-42", "name": "finans"}]},
                    },
                }
            ]
        }
    )

    connector = _connector(default_acl=("space:AUR",))
    checkpoint: dict[str, object] = {}
    documents = [doc async for doc in connector.crawl(checkpoint)]
    await connector.aclose()

    assert [doc.source_ref for doc in documents] == ["wiki://p1@3", "wiki://p2@3"]
    # Unrestricted page inherits the connection default; restricted page narrows to
    # the enumerated principals ONLY (the pre-filter must never widen access).
    assert documents[0].acl_keys == ("space:AUR",)
    assert documents[1].acl_keys == ("confluence-user:acc-1", "confluence-group:g-42")
    assert documents[0].freshness_at is not None
    assert documents[0].freshness_at.year == 2026
    assert "[AUR]" in documents[0].title
    assert str(checkpoint["last_modified"]).startswith("2026-07-01T10:00:00")
    assert "space_index" not in checkpoint  # completed full crawl → incremental next


@pytest.mark.asyncio
@respx.mock
async def test_incremental_crawl_uses_cql_and_advances_checkpoint() -> None:
    search = respx.get(f"{BASE}/wiki/rest/api/search").respond(
        json={
            "results": [
                {
                    "content": {"id": "p9", "version": {"when": "2026-08-01T09:00:00Z"}},
                    "lastModified": "2026-08-01T09:00:00Z",
                }
            ],
            "_links": {},
        }
    )
    respx.get(f"{BASE}/wiki/api/v2/pages/p9").respond(json=_page_payload("p9", "Yeni"))
    respx.get(f"{BASE}/wiki/rest/api/content/p9/restriction").respond(json=_no_restrictions())

    connector = _connector()
    checkpoint: dict[str, object] = {"last_modified": "2026-07-15T00:00:00Z"}
    documents = [doc async for doc in connector.crawl(checkpoint)]
    await connector.aclose()

    assert len(documents) == 1
    cql = search.calls[0].request.url.params["cql"]
    assert "lastmodified >=" in cql and "order by lastmodified asc" in cql
    assert 'space in ("AUR")' in cql
    # Watermark advances to the newest edit (stored as ISO-UTC).
    assert str(checkpoint["last_modified"]).startswith("2026-08-01T09:00:00")


@pytest.mark.asyncio
@respx.mock
async def test_rate_limit_retry_after_honored() -> None:
    route = respx.get(f"{BASE}/wiki/api/v2/spaces")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0"}),
        httpx.Response(200, json={"results": [], "_links": {}}),
    ]
    connector = _connector()
    checkpoint: dict[str, object] = {}
    documents = [doc async for doc in connector.crawl(checkpoint)]
    await connector.aclose()
    assert documents == []
    assert route.call_count == 2  # 429 obeyed, then retried
