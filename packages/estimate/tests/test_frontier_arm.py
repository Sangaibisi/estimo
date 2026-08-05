"""The frontier eval arm (S13-6): opt-in, measured, anchor-redacted."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from estimo_estimate.evals import leave_one_out, render_report
from estimo_knowledge import import_seed
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from estimo_gateway import GatewayClient, GatewayConfig

REPO_ROOT = Path(__file__).resolve().parents[3]
SEED = REPO_ROOT / "fixtures" / "seed" / "sample-seed.csv"
BASE_URL = "http://frontier.invalid/v1"


def _completion(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "c",
            "object": "chat.completion",
            "created": 1,
            "model": "m",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )


pytestmark = pytest.mark.db


def _client() -> GatewayClient:
    return GatewayClient(
        GatewayConfig(
            base_url=BASE_URL, api_key=SecretStr("sk-test"), profiles={"default": "balanced"}
        )
    )


@pytest.fixture
async def seeded(session: AsyncSession, clean_tables: None) -> AsyncSession:
    report = await import_seed(session, SEED)
    assert report.rejected == []
    return session


@respx.mock
async def test_the_frontier_arm_is_measured_beside_the_calibrated_arm(
    seeded: AsyncSession,
) -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8")
        assert "ESTIMO-FRONTIER" in body
        # PRINCIPLES #5 holds for eval traffic too: the seed's planted effort
        # anchors must never reach the free-form arm.
        assert "adam-gün" not in body
        return _completion('{"optimistic": 3, "likely": 6, "pessimistic": 12}')

    respx.post(f"{BASE_URL}/chat/completions").mock(side_effect=responder)
    client = _client()
    try:
        result = await leave_one_out(seeded, client=client, frontier=True)
    finally:
        await client.aclose()

    # The calibrated arm is untouched by the extra arm.
    assert result.cases >= 10
    assert result.mae <= result.naive_mae + 0.5
    # The frontier arm answered every completed row (it does not need analogs).
    assert result.frontier_cases >= result.cases
    assert result.frontier_failed == 0
    assert result.frontier_mae > 0
    assert result.prompt_ids == ["frontier-v1"]

    report = render_report(result, today="2026-08-05")
    assert "Frontier arm" in report
    assert "frontier-v1" in report
    payload = result.as_dict()
    frontier = payload["frontier"]
    assert isinstance(frontier, dict) and frontier["cases"] == result.frontier_cases


@respx.mock
async def test_frontier_failures_drop_out_of_its_average_only(seeded: AsyncSession) -> None:
    respx.post(f"{BASE_URL}/chat/completions").mock(
        side_effect=lambda request: _completion("free-form prose, not a band")
    )
    client = _client()
    try:
        result = await leave_one_out(seeded, client=client, frontier=True)
    finally:
        await client.aclose()
    assert result.frontier_cases == 0
    assert result.frontier_failed > 0
    assert result.cases >= 10, "a broken frontier arm damaged the calibrated arm"


async def test_the_default_run_is_offline(seeded: AsyncSession) -> None:
    # No respx mock active: any network attempt would raise. This is the CI path.
    result = await leave_one_out(seeded)
    assert result.frontier_cases == 0 and result.frontier_failed == 0
    assert result.as_dict()["frontier"] is None
