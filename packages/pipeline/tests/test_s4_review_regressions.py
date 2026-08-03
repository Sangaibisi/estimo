"""Regressions for the confirmed findings of the S4 adversarial review."""

from pathlib import Path

import pytest
import respx
from estimo_parse import redact_anchors
from estimo_pipeline import resume_with_answers, run_brd
from estimo_pipeline.nodes import _answer_clears, decompose
from estimo_pipeline.state import PipelineState
from pydantic import SecretStr

from estimo_core import Requirement
from estimo_gateway import GatewayClient, GatewayConfig

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "brd"
BASE_URL = "http://gateway.local/v1"


class TestAnswerQualityGate:
    """Finding 1 (critical): answers must survive the gate themselves."""

    def test_non_answers_do_not_clear(self) -> None:
        for garbage in ("-", "bilmiyorum", "yok", "tbd", "sonra bakarız belki olabilir"):
            assert not _answer_clears(garbage), garbage

    def test_vague_answer_does_not_clear(self) -> None:
        assert not _answer_clears("Koşullar gerekiyorsa daha sonra netleştirilecektir.")

    def test_substantive_answer_clears(self) -> None:
        assert _answer_clears(
            "Kurumsal müşterilerde taksit sayısı 6 ile sınırlıdır ve komisyon oranı %5 sabittir."
        )

    async def test_garbage_answer_keeps_item_blocked(self) -> None:
        state = await run_brd(FIXTURES / "BRD-AUR-26-01-taksitlendirme.docx")
        resumed = await resume_with_answers(state, {"Q-REQ-G-04": "bilmiyorum"})
        assert "REQ-G-04" in resumed.blocked_ids


class TestAnchorQuarantine:
    """Finding 2 (critical): anchor snippets must never reach LLM payloads."""

    def test_redaction_uses_detection_patterns(self) -> None:
        text = (
            "Bu iş için ayrılan bütçe azami 90 adam-gündür. Kampanya lansmanı "
            "30 Eylül 2026 tarihine yetişmelidir. Fatura kalemi eklenmelidir."
        )
        redacted = redact_anchors(text)
        assert "90 adam-gün" not in redacted
        assert "30 Eylül" not in redacted
        assert "budget-karantina" in redacted
        assert "Fatura kalemi eklenmelidir" in redacted

    @respx.mock
    async def test_no_anchor_reaches_any_llm_payload(self) -> None:
        route = respx.post(f"{BASE_URL}/chat/completions").respond(
            200,
            json={
                "id": "c",
                "object": "chat.completion",
                "created": 1,
                "model": "balanced",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "{}"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )
        client = GatewayClient(
            GatewayConfig(
                base_url=BASE_URL,
                api_key=SecretStr("sk-test"),
                profiles={"default": "balanced"},
            )
        )
        try:
            await run_brd(
                FIXTURES / "BRD-AUR-26-01-taksitlendirme.docx",
                client=client,
                thread_id="anchor-leak",
            )
        finally:
            await client.aclose()
        for call in route.calls:
            payload = call.request.content.decode("utf-8")
            assert "90 adam-gün" not in payload, "budget anchor leaked into an LLM prompt"
            assert "30 Eylül" not in payload, "deadline anchor leaked into an LLM prompt"


class TestTitleFallback:
    """Finding 3 (major): leading-dot requirement text must not crash decompose."""

    async def test_leading_dot_title(self) -> None:
        req = Requirement(id="REQ-NET-1", text=".NET servisinde loglama eklenmelidir")
        state = PipelineState(source_path="x", requirements=(req,), status="gated")
        result = await decompose(state)
        assert len(result.work_items) == 1
        assert result.work_items[0].title.strip()


class TestResumeValidation:
    """Finding 5 (minor): hand-edited answers JSON is validated loudly."""

    async def test_unknown_question_id_rejected(self) -> None:
        state = await run_brd(FIXTURES / "BRD-AUR-26-01-taksitlendirme.docx")
        with pytest.raises(ValueError, match="unknown question ids"):
            await resume_with_answers(state, {"Q-TYPO": "cevap metni yeterince uzun"})

    async def test_non_string_answer_rejected(self) -> None:
        state = await run_brd(FIXTURES / "BRD-AUR-26-01-taksitlendirme.docx")
        with pytest.raises(Exception, match="valid"):
            await resume_with_answers(state, {"Q-REQ-G-04": 42})  # type: ignore[dict-item]
