"""Pipeline behavior: offline determinism, the gate law, HITL resume, LLM degradation."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import respx
from estimo_pipeline import (
    AURORA_MODULES,
    load_prompt,
    modules_for,
    resume_with_answers,
    run_brd,
)
from pydantic import SecretStr

from estimo_gateway import GatewayClient, GatewayConfig

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "brd"
BASE_URL = "http://gateway.local/v1"


class TestPrompts:
    def test_prompts_are_versioned(self) -> None:
        questions = load_prompt("questions")
        decompose = load_prompt("decompose")
        assert questions.id == "questions-v1"
        assert decompose.id == "decompose-v1"
        assert questions.text.count("→") >= 10, "needs 10+ few-shot examples (S4-4)"

    def test_missing_header_fails_loudly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import estimo_pipeline.prompts as prompts_module

        bad = tmp_path / "rogue.md"
        bad.write_text("no header here", encoding="utf-8")
        monkeypatch.setattr(prompts_module, "PROMPTS_DIR", tmp_path)
        with pytest.raises(ValueError, match="header"):
            prompts_module.load_prompt("rogue")


class TestTaxonomy:
    def test_primary_module_order(self) -> None:
        assert modules_for("Kampanya bazında komisyon oranları uygulanmalıdır")[0] == (
            "campaign-engine"
        )
        assert modules_for("Fatura üretilmelidir")[0] == "billing-core"
        assert modules_for("hiç eşleşmeyen metin xyz") == ()
        assert AURORA_MODULES == frozenset(
            {
                "billing-core",
                "crm-suite",
                "product-catalog",
                "campaign-engine",
                "dealer-portal",
                "integration-hub",
                "payment-adapter",
                "invoice-render",
                "selfcare-web",
            }
        )


class TestOfflinePipeline:
    async def test_clean_brd_flows_to_estimation_ready(self) -> None:
        state = await run_brd(FIXTURES / "BRD-AUR-26-02-konsolide-fatura.docx")
        assert state.status == "ready_for_estimation"
        assert state.blocked_ids == ()
        assert len(state.work_items) == 6
        assert all(item.module_tags for item in state.work_items)

    async def test_gate_blocks_and_questions_cover(self) -> None:
        state = await run_brd(FIXTURES / "BRD-AUR-26-01-taksitlendirme.docx")
        assert state.status == "awaiting_answers"
        assert "REQ-G-04" in state.blocked_ids
        question_reqs = {q.requirement_id for q in state.questions}
        assert set(state.blocked_ids) <= question_reqs
        # The gate law: no blocked requirement may own a work item (PRINCIPLES #3).
        item_reqs = {r for item in state.work_items for r in item.requirement_ids}
        assert item_reqs.isdisjoint(state.blocked_ids)

    async def test_determinism(self) -> None:
        first = await run_brd(FIXTURES / "BRD-AUR-26-01-taksitlendirme.docx", thread_id="a")
        second = await run_brd(FIXTURES / "BRD-AUR-26-01-taksitlendirme.docx", thread_id="b")
        assert [i.model_dump() for i in first.work_items] == [
            i.model_dump() for i in second.work_items
        ]
        assert first.blocked_ids == second.blocked_ids


class TestResume:
    async def test_answer_clears_gate_and_item_appears(self) -> None:
        state = await run_brd(FIXTURES / "BRD-AUR-26-01-taksitlendirme.docx")
        assert "REQ-G-04" in state.blocked_ids
        answer = {
            "Q-REQ-G-04": (
                "Kurumsal müşterilerde taksit sayısı 6 ile sınırlıdır ve komisyon "
                "oranı %5 sabittir; uygunluk kriteri bireysel ile aynıdır."
            )
        }
        resumed = await resume_with_answers(state, answer)
        assert "REQ-G-04" not in resumed.blocked_ids
        assert resumed.status == "ready_for_estimation"
        item_reqs = {r for item in resumed.work_items for r in item.requirement_ids}
        assert "REQ-G-04" in item_reqs

    async def test_empty_answer_does_not_clear(self) -> None:
        state = await run_brd(FIXTURES / "BRD-AUR-26-01-taksitlendirme.docx")
        resumed = await resume_with_answers(state, {"Q-REQ-G-04": "   "})
        assert "REQ-G-04" in resumed.blocked_ids


def _completion(content: str) -> dict[str, object]:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1_700_000_000,
        "model": "balanced",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130},
    }


@pytest.fixture
async def gateway() -> AsyncIterator[GatewayClient]:
    client = GatewayClient(
        GatewayConfig(
            base_url=BASE_URL,
            api_key=SecretStr("sk-test"),
            profiles={"default": "balanced"},
        )
    )
    yield client
    await client.aclose()


class TestLlmPaths:
    @respx.mock
    async def test_llm_question_used_when_valid(self, gateway: GatewayClient) -> None:
        respx.post(f"{BASE_URL}/chat/completions").respond(
            200,
            json=_completion(
                '{"question": "Kurumsal segment için taksit koşullarının hangi başlıklarda '
                'farklılaşacağını netleştirebilir misiniz?", "reason": "Segment tanımsız."}'
            ),
        )
        state = await run_brd(
            FIXTURES / "BRD-AUR-26-01-taksitlendirme.docx", client=gateway, thread_id="llm"
        )
        question = next(q for q in state.questions if q.requirement_id == "REQ-G-04")
        assert "Kurumsal segment" in question.question

    @respx.mock
    async def test_llm_garbage_degrades_to_template(self, gateway: GatewayClient) -> None:
        respx.post(f"{BASE_URL}/chat/completions").respond(
            200, json=_completion("tabii, elbette yardımcı olayım ama json veremem")
        )
        state = await run_brd(
            FIXTURES / "BRD-AUR-26-01-taksitlendirme.docx", client=gateway, thread_id="llm2"
        )
        question = next(q for q in state.questions if q.requirement_id == "REQ-G-04")
        assert question.question.endswith("?")  # deterministic template held the line

    @respx.mock
    async def test_gateway_down_never_breaks_pipeline(self, gateway: GatewayClient) -> None:
        respx.post(f"{BASE_URL}/chat/completions").respond(500, json={"error": {"message": "x"}})
        state = await run_brd(
            FIXTURES / "BRD-AUR-26-02-konsolide-fatura.docx", client=gateway, thread_id="down"
        )
        assert state.status == "ready_for_estimation"
        assert len(state.work_items) == 6
