"""The ACL pre-filter must never take its permissions from the requester.

SECURITY.md: "source ACLs … are carried in chunk metadata and enforced as a
**pre-filter** at query time". Before this suite existed, `POST /v1/canonical` passed
the request body's `acl_keys` straight into `lexical_chunk_ids`, so any reviewer could
name a restricted audience, have its text distilled into a draft body, and read that
body back from `GET /v1/canonical`. These tests pin the clamp shut.
"""

from collections.abc import AsyncIterator

import httpx
import pytest
from _helpers import make_settings
from asgi_lifespan import LifespanManager
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from estimo_api.auth import Principal, clamp_acl_keys
from estimo_api.main import create_app

pytestmark = pytest.mark.db

RESTRICTED = "confluence-group:finans"
SECRET_TEXT = "Taksitlendirme marj tablosu yalnız finans ekibine açıktır."


@pytest.fixture
async def client(database_url: str, clean_tables: None) -> AsyncIterator[httpx.AsyncClient]:
    engine = create_async_engine(database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        from estimo_knowledge import upsert_document

        await upsert_document(
            session,
            source_type="confluence",
            source_ref="wiki://restricted@1",
            title="Marj tablosu",
            text=SECRET_TEXT,
            acl_keys=[RESTRICTED],
        )
        await session.commit()
    await engine.dispose()

    app = create_app(make_settings(database_url))
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


async def test_candidate_cannot_source_from_an_audience_the_caller_lacks(
    client: httpx.AsyncClient,
) -> None:
    """The escalation itself: naming a restricted key must be refused, not honoured."""
    response = await client.post(
        "/v1/canonical",
        json={"topic": "taksitlendirme marj tablosu", "acl_keys": [RESTRICTED]},
    )
    assert response.status_code == 403, response.text
    assert RESTRICTED in response.json()["detail"] or "acl_keys" in response.json()["detail"]

    # And nothing leaked into a page anyone can read back.
    listed = await client.get("/v1/canonical")
    assert listed.status_code == 200
    assert SECRET_TEXT not in listed.text


async def test_unrequested_candidate_is_built_from_public_sources_only(
    client: httpx.AsyncClient,
) -> None:
    """Omitting acl_keys must fall back to the caller's own audiences, not to
    'everything' — a silent widening would be the same bug with a shorter payload."""
    response = await client.post("/v1/canonical", json={"topic": "taksitlendirme marj tablosu"})
    assert response.status_code in (201, 422), response.text
    listed = await client.get("/v1/canonical")
    assert SECRET_TEXT not in listed.text


def test_clamp_intersects_and_never_widens() -> None:
    entitled = Principal(
        subject="s", tenant="t", roles=frozenset({"reviewer"}), acl_keys=frozenset({"public", "a"})
    )
    assert clamp_acl_keys(entitled, None) == ["a", "public"]
    assert clamp_acl_keys(entitled, ["a"]) == ["a"]
    assert clamp_acl_keys(entitled, ["a", "b"]) == ["a"], "an unheld key must be dropped"
    with pytest.raises(Exception, match="acl_keys"):
        clamp_acl_keys(entitled, ["b"])


def test_open_mode_admin_is_not_entitled_to_every_audience() -> None:
    """Single-tenant open mode grants every ROLE but no extra ACL audience: ACL keys
    model the SOURCE system's permissions, and Estimo's users are a superset of the
    people who may read a restricted Confluence space even when Estimo is open."""
    from estimo_api.auth import ROLES

    local = Principal(subject="local", tenant="t", roles=frozenset(ROLES))
    assert local.acl_keys == frozenset({"public"})
    with pytest.raises(Exception, match="acl_keys"):
        clamp_acl_keys(local, [RESTRICTED])
