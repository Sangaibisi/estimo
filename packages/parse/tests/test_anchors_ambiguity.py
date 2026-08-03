"""Unit behavior of anchor detection and the ambiguity scorer (incl. LLM blend)."""

from collections.abc import AsyncIterator

import pytest
import respx
from estimo_parse import blend, detect_anchors, llm_score, rule_score
from pydantic import SecretStr

from estimo_core import Requirement
from estimo_gateway import GatewayClient, GatewayConfig

BASE_URL = "http://gateway.local/v1"


def req(text: str, **overrides: object) -> Requirement:
    base: dict[str, object] = {"id": "REQ-T-01", "text": text}
    base.update(overrides)
    return Requirement.model_validate(base)


class TestAnchors:
    def test_budget_anchor(self) -> None:
        anchors = detect_anchors("Bu iş için ayrılan bütçe azami 90 adam-gündür.")
        assert [a.type for a in anchors] == ["budget"]
        assert "90 adam-gün" in anchors[0].snippet

    def test_deadline_anchor(self) -> None:
        anchors = detect_anchors("Kampanya lansmanı 30 Eylül 2026 tarihine yetişmelidir.")
        assert [a.type for a in anchors] == ["deadline"]

    def test_analogy_anchor_not_double_counted_as_hint(self) -> None:
        anchors = detect_anchors(
            "Benzer bir entegrasyonu geçen yıl başka bir tedarikçiyle 40 günde "
            "tamamlamıştık; bu işin de benzer sürede biteceğini düşünüyoruz."
        )
        assert [a.type for a in anchors] == ["analogy"]

    def test_clean_text_has_no_anchors(self) -> None:
        assert detect_anchors("Taksit planları 3, 6 ve 12 ay seçenekleriyle sunulmalıdır.") == ()


class TestRuleScore:
    def test_vague_terms_raise_score(self) -> None:
        score, issues = rule_score(req("Kurumsal müşteriler için farklı koşullar uygulanabilir."))
        assert score >= 0.5
        assert any(issue.startswith("vague-terms") for issue in issues)

    def test_acceptance_criteria_lower_score(self) -> None:
        without, _ = rule_score(req("Cihaz iadesi durumunda taksit planı kapatılmalıdır."))
        with_acc, _ = rule_score(
            req(
                "Cihaz iadesi durumunda taksit planı kapatılmalıdır.",
                acceptance_criteria="İade sonrası ilk faturada taksit kalemi görünmez.",
                extraction="table",
            )
        )
        assert with_acc < without

    def test_heuristic_extraction_penalized(self) -> None:
        coded, _ = rule_score(req("Sipariş özeti panoya günlük düşmelidir."))
        heuristic, issues = rule_score(
            req("Sipariş özeti panoya günlük düşmelidir.", extraction="heuristic")
        )
        assert heuristic == pytest.approx(coded + 0.2)
        assert "unstructured-source" in issues


@pytest.fixture
async def gateway() -> AsyncIterator[GatewayClient]:
    client = GatewayClient(
        GatewayConfig(
            base_url=BASE_URL,
            api_key=SecretStr("sk-test"),
            profiles={"reading": "precise-long"},
        )
    )
    yield client
    await client.aclose()


def llm_body(content: str) -> dict[str, object]:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1_700_000_000,
        "model": "precise-long",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
    }


class TestLlmBlend:
    @respx.mock
    async def test_llm_refines_upward_only(self, gateway: GatewayClient) -> None:
        respx.post(f"{BASE_URL}/chat/completions").respond(
            200, json=llm_body('{"score": 0.9, "issues": ["missing-actor"]}')
        )
        requirement = req("Sistem entegrasyonu yapılmalıdır.")
        rule = rule_score(requirement)
        llm = await llm_score(gateway, requirement)
        score, issues = blend(rule, llm)
        assert score == 0.9
        assert "missing-actor" in issues
        assert all(issue in issues for issue in rule[1])

    @respx.mock
    async def test_unparseable_llm_output_never_masks_rule_floor(
        self, gateway: GatewayClient
    ) -> None:
        respx.post(f"{BASE_URL}/chat/completions").respond(
            200, json=llm_body("elbette! işte değerlendirmem: yüksek belirsizlik var")
        )
        requirement = req("Kurumsal müşteriler için farklı koşullar uygulanabilir.")
        rule = rule_score(requirement)
        llm = await llm_score(gateway, requirement)
        score, issues = blend(rule, llm)
        assert score == rule[0]
        assert "llm-output-unparseable" in issues

    @respx.mock
    async def test_llm_score_clamped(self, gateway: GatewayClient) -> None:
        respx.post(f"{BASE_URL}/chat/completions").respond(
            200, json=llm_body('{"score": 7.5, "issues": []}')
        )
        score, _ = await llm_score(gateway, req("x " * 10))
        assert score == 1.0
