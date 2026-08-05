"""The agentic impact worker (S13-2): protocol, verification, degradation.

No DB: the scripts only exercise search_code + finalize, so the session parameter
is never touched. The graph is the real meridyen-mini fixture — the same estate the
code-shelf eval uses — so evidence URIs are produced by the actual builder, not
hand-typed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import httpx
import pytest
import respx
from estimo_code import CodeGraph
from estimo_estimate.impact_worker import (
    _resolves_in_graphs,
    _search_code,
    analyze_impact,
    deterministic_analysis,
)
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from estimo_core import Confidence, WorkItem
from estimo_gateway import GatewayClient, GatewayConfig

REPO = Path(__file__).resolve().parents[3] / "fixtures" / "repo" / "meridyen-mini"
BASE_URL = "http://impact.invalid/v1"

_NO_SESSION = cast(AsyncSession, None)


@pytest.fixture(scope="module")
def graph() -> CodeGraph:
    return CodeGraph.build(REPO, repo="meridyen-mini", commit="c0ffee")


def _item() -> WorkItem:
    return WorkItem(
        id="WI-01",
        brd_ref="BRD-TEST",
        title="Taksitli fatura planı",
        description="Kampanya bazlı taksit planı desteklenecek",
        requirement_ids=("REQ-01",),
    )


def _client() -> GatewayClient:
    return GatewayClient(
        GatewayConfig(
            base_url=BASE_URL, api_key=SecretStr("sk-test"), profiles={"default": "balanced"}
        )
    )


def _completion(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "created": 1,
            "model": "m",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )


class TestTools:
    def test_search_code_finds_symbols_without_synonyms(self, graph: CodeGraph) -> None:
        hits = _search_code([graph], "installment plan")
        assert hits, "the fixture repo has installment symbols"
        assert all(hit["uri"].startswith("repo://meridyen-mini@c0ffee/") for hit in hits)
        # Turkish terms deliberately find nothing here — the bridging is the
        # model's job now, not a dictionary's.
        assert _search_code([graph], "taksit") == []

    def test_repo_uri_resolution_is_exact(self, graph: CodeGraph) -> None:
        uri = _search_code([graph], "installment")[0]["uri"]
        assert _resolves_in_graphs(uri, [graph])
        assert not _resolves_in_graphs(uri.replace("@c0ffee", "@stale00"), [graph])
        assert not _resolves_in_graphs(
            "repo://meridyen-mini@c0ffee/no/such/File.java#L1-L2", [graph]
        )
        assert not _resolves_in_graphs("wiki://123@4", [graph])


class TestLoop:
    @respx.mock
    async def test_a_scripted_run_keeps_verified_claims(self, graph: CodeGraph) -> None:
        code_uri = _search_code([graph], "installment")[0]["uri"]
        finalize = {
            "action": "finalize",
            "analysis": {
                "repos": ["meridyen-mini", "not-a-repo"],
                "modules": [
                    {
                        "text": "Taksit planı billing-core modülüne dokunur.",
                        "module": "billing-core",
                        "evidence": [code_uri],
                    }
                ],
                "integration_points": [],
                "discovery_risks": [],
                "composition": [
                    {"discipline": "frontend", "share": 0.3, "rationale": "ekran işi"},
                    {"discipline": "backend", "share": 0.7, "rationale": "plan motoru"},
                ],
                "confidence": "high",
            },
        }
        route = respx.post(f"{BASE_URL}/chat/completions").mock(
            side_effect=[
                _completion('{"action": "search_code", "query": "installment plan"}'),
                _completion(json.dumps(finalize)),
            ]
        )
        client = _client()
        try:
            analysis = await analyze_impact(
                _NO_SESSION, _item(), "Taksitli fatura planı", [graph], client=client
            )
        finally:
            await client.aclose()

        assert analysis.source == "agentic"
        assert analysis.modules[0].evidence[0].uri == code_uri
        assert analysis.modules[0].module == "billing-core"
        assert analysis.composition[1].share == 0.7
        assert analysis.confidence is Confidence.HIGH
        assert analysis.dropped_claims == 0
        # The invented repo name was filtered against the loaded estate.
        assert analysis.repos == ("meridyen-mini",)
        # The second request carried the tool result back to the model.
        second_body = route.calls[1].request.content.decode("utf-8")
        assert "Result of search_code" in second_body
        assert code_uri in second_body

    @respx.mock
    async def test_fabricated_evidence_is_dropped_and_counted(self, graph: CodeGraph) -> None:
        finalize = {
            "action": "finalize",
            "analysis": {
                "modules": [
                    {
                        "text": "Uydurma dosyaya atıf.",
                        "module": "billing-core",
                        "evidence": ["repo://meridyen-mini@c0ffee/fake/File.java#L1-L2"],
                    },
                    {
                        "text": "Görülmemiş wiki sayfası.",
                        "evidence": ["wiki://9999@1"],
                    },
                ],
                "confidence": "high",
            },
        }
        respx.post(f"{BASE_URL}/chat/completions").mock(
            side_effect=[_completion(json.dumps(finalize))]
        )
        client = _client()
        try:
            analysis = await analyze_impact(
                _NO_SESSION, _item(), "Taksitli fatura planı", [graph], client=client
            )
        finally:
            await client.aclose()

        assert analysis.source == "agentic"
        assert analysis.modules == ()
        assert analysis.dropped_claims == 2

    @respx.mock
    async def test_two_unparseable_turns_fall_back_to_deterministic(self, graph: CodeGraph) -> None:
        respx.post(f"{BASE_URL}/chat/completions").mock(
            side_effect=[_completion("I think the modules are..."), _completion("sorry, prose")]
        )
        client = _client()
        try:
            analysis = await analyze_impact(
                _NO_SESSION,
                _item(),
                "Kampanya bazlı taksit planı desteği eklenmelidir",
                [graph],
                client=client,
            )
        finally:
            await client.aclose()

        assert analysis.source == "deterministic"
        # The fallback still finds the installment modules — via the synonym
        # dictionary, which survives exactly here.
        assert analysis.modules

    @respx.mock
    async def test_a_dead_gateway_falls_back_to_deterministic(self, graph: CodeGraph) -> None:
        respx.post(f"{BASE_URL}/chat/completions").mock(side_effect=httpx.ConnectError("refused"))
        client = _client()
        try:
            analysis = await analyze_impact(
                _NO_SESSION,
                _item(),
                "Kampanya bazlı taksit planı desteği eklenmelidir",
                [graph],
                client=client,
            )
        finally:
            await client.aclose()
        assert analysis.source == "deterministic"

    @respx.mock
    async def test_a_broken_composition_costs_the_split_not_the_analysis(
        self, graph: CodeGraph
    ) -> None:
        code_uri = _search_code([graph], "installment")[0]["uri"]
        finalize = {
            "action": "finalize",
            "analysis": {
                "modules": [
                    {"text": "Geçerli iddia.", "module": "billing-core", "evidence": [code_uri]}
                ],
                "composition": [{"discipline": "frontend", "share": 0.2}],  # sums to 0.2
                "confidence": "medium",
            },
        }
        respx.post(f"{BASE_URL}/chat/completions").mock(
            side_effect=[_completion(json.dumps(finalize))]
        )
        client = _client()
        try:
            analysis = await analyze_impact(
                _NO_SESSION, _item(), "Taksitli fatura planı", [graph], client=client
            )
        finally:
            await client.aclose()
        assert analysis.source == "agentic"
        assert analysis.modules
        assert analysis.composition == ()

    async def test_no_client_is_the_deterministic_path(self, graph: CodeGraph) -> None:
        analysis = await analyze_impact(
            _NO_SESSION,
            _item(),
            "Kampanya bazlı taksit planı desteği eklenmelidir",
            [graph],
            client=None,
        )
        assert analysis.source == "deterministic"
        assert analysis == deterministic_analysis(
            _item(), "Kampanya bazlı taksit planı desteği eklenmelidir", [graph]
        )
