"""S7 backend: the estimate workflow API, with server-enforced independent-first."""

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
from _helpers import make_settings
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from estimo_api.main import create_app

pytestmark = pytest.mark.db

REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = Path(__file__).parents[1] / "alembic.ini"
FIXTURES = REPO_ROOT / "fixtures" / "brd"
SEED = REPO_ROOT / "fixtures" / "seed" / "sample-seed.csv"


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    url = os.environ["ESTIMO_TEST_DATABASE_URL"]
    os.environ["ESTIMO_DATABASE_URL"] = url
    command.upgrade(Config(str(ALEMBIC_INI)), "head")
    yield url


@pytest.fixture
async def client(database_url: str) -> AsyncIterator[httpx.AsyncClient]:
    engine = create_async_engine(database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        await session.execute(text("TRUNCATE estimates, ledger_entries, knowledge_chunks CASCADE"))
        await session.commit()
        from estimo_knowledge import import_seed

        await import_seed(session, SEED)
    await engine.dispose()

    app = create_app(make_settings(database_url))
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


async def _upload(client: httpx.AsyncClient, name: str) -> dict[str, object]:
    path = FIXTURES / name
    response = await client.post(
        "/v1/estimates",
        files={
            "file": (
                name,
                path.read_bytes(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


async def test_full_workflow_clean_brd(client: httpx.AsyncClient) -> None:
    summary = await _upload(client, "BRD-AUR-26-02-konsolide-fatura.docx")
    assert summary["status"] == "ready_for_estimation"
    assert summary["work_items"] == 6
    estimate_id = summary["id"]

    built = await client.post(f"/v1/estimates/{estimate_id}/estimate")
    assert built.status_code == 200
    assert built.json()["critic"] == []
    assert len(built.json()["boe"]["lines"]) == 6

    # Independent-first: no AI band before the estimator's own band exists.
    desk = (
        await client.get(f"/v1/estimates/{estimate_id}/desk", params={"estimator": "D. Aksoy"})
    ).json()
    first_item = desk["items"][0]
    assert first_item["ai"] is None
    item_id = first_item["work_item"]["id"]

    recorded = await client.post(
        f"/v1/estimates/{estimate_id}/independent",
        json={
            "work_item_id": item_id,
            "estimator": "D. Aksoy",
            "optimistic": 5,
            "likely": 8,
            "pessimistic": 13,
        },
    )
    assert recorded.status_code == 201

    duplicate = await client.post(
        f"/v1/estimates/{estimate_id}/independent",
        json={
            "work_item_id": item_id,
            "estimator": "D. Aksoy",
            "optimistic": 1,
            "likely": 2,
            "pessimistic": 3,
        },
    )
    assert duplicate.status_code == 409  # immutable: anchoring telemetry integrity

    desk = (
        await client.get(f"/v1/estimates/{estimate_id}/desk", params={"estimator": "D. Aksoy"})
    ).json()
    revealed = next(i for i in desk["items"] if i["work_item"]["id"] == item_id)
    assert revealed["ai"] is not None
    assert revealed["delta_likely"] is not None
    others = [i for i in desk["items"] if i["work_item"]["id"] != item_id]
    assert all(i["ai"] is None for i in others)  # reveal is per item, per estimator

    signed = await client.post(
        f"/v1/estimates/{estimate_id}/sign",
        json={"work_item_id": item_id, "name": "D. Aksoy", "role": "Reviewer"},
    )
    assert signed.status_code == 201

    docx = await client.get(f"/v1/estimates/{estimate_id}/boe.docx")
    assert docx.status_code == 200
    assert docx.content[:2] == b"PK"  # a zip container => real .docx


async def test_answers_flow_and_boe_invalidation(client: httpx.AsyncClient) -> None:
    summary = await _upload(client, "BRD-AUR-26-01-taksitlendirme.docx")
    assert summary["status"] == "awaiting_answers"
    estimate_id = summary["id"]

    premature = await client.post(f"/v1/estimates/{estimate_id}/estimate")
    assert premature.status_code == 409  # PRINCIPLES #3 at the API boundary

    answered = await client.post(
        f"/v1/estimates/{estimate_id}/answers",
        json={
            "answers": {
                "Q-REQ-G-04": (
                    "Kurumsal müşterilerde taksit sayısı 6 ile sınırlıdır ve komisyon "
                    "oranı %5 sabittir."
                )
            }
        },
    )
    assert answered.status_code == 200
    assert answered.json()["status"] == "ready_for_estimation"

    unknown = await client.post(
        f"/v1/estimates/{estimate_id}/answers", json={"answers": {"Q-TYPO": "x" * 30}}
    )
    assert unknown.status_code == 422


async def test_upload_rejects_non_docx(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/estimates", files={"file": ("brd.txt", b"plain", "text/plain")}
    )
    assert response.status_code == 422


async def test_event_capture(client: httpx.AsyncClient) -> None:
    summary = await _upload(client, "BRD-AUR-26-04-bakiye-tasima.docx")
    response = await client.post(
        f"/v1/estimates/{summary['id']}/events",
        json={"kind": "section-edit", "payload": {"section": "assumptions", "distance": 12}},
    )
    assert response.status_code == 201
