"""Number policy (S13-4): vetting, nudge context, no-analog proposal.

Unit tests drive the functions with respx; the two estimator-level tests prove the
WIRING — reverting either call site (vetting before the band, proposal in the
no-analog branch) turns them red, which is the regression the S13-2 MUTANT
incident taught us to demand.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import httpx
import pytest
import respx
from estimo_estimate import estimate_state
from estimo_estimate.number_policy import (
    MODEL_PROPOSED_BASIS,
    analog_context,
    cone_widened,
    propose_no_analog_band,
    vet_analogs,
)
from estimo_knowledge import AnalogyCard, import_seed
from estimo_pipeline import run_brd
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from estimo_core import ConeStage, ThreePoint
from estimo_gateway import GatewayClient, GatewayConfig

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "fixtures" / "brd"
SEED = REPO_ROOT / "fixtures" / "seed" / "sample-seed.csv"
BASE_URL = "http://numbers.invalid/v1"


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
            "id": "c",
            "object": "chat.completion",
            "created": 1,
            "model": "m",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )


def _card(name: str, actual: float) -> AnalogyCard:
    return AnalogyCard(
        entry_id=uuid.uuid5(uuid.NAMESPACE_URL, name),
        rank=1,
        similarity=None,
        brd_ref=f"BRD-{name}",
        item_title=f"Analog {name}",
        module_tags=("billing-core",),
        domain_tags=(),
        team=None,
        method="expert",
        estimate=None,
        estimate_single=None,
        actual_effort=actual,
        actual_source="timesheet",
        scope_changed=False,
        deviation=None,
    )


class TestConeWidening:
    def test_a_narrow_proposal_is_widened_to_the_cone_floor(self) -> None:
        band = cone_widened(4.0, 5.0, 6.0, ConeStage.CONCEPT)
        assert band.optimistic == round(5.0 / 4.0, 1)
        assert band.pessimistic == 20.0

    def test_a_wide_proposal_keeps_its_width(self) -> None:
        band = cone_widened(0.5, 5.0, 40.0, ConeStage.CONCEPT)
        assert band.optimistic == 0.5
        assert band.pessimistic == 40.0


class TestVetting:
    @respx.mock
    async def test_exclusions_leave_the_median_and_land_in_the_register(self) -> None:
        cards = [_card("a", 10.0), _card("b", 11.0), _card("poison", 90.0)]
        verdicts = {
            "verdicts": [
                {
                    "entry_id": str(cards[2].entry_id),
                    "comparable": False,
                    "reason": "Farklı iş türü: veri migrasyonu.",
                },
                {"entry_id": str(uuid.uuid4()), "comparable": False, "reason": "uydurma"},
            ]
        }
        respx.post(f"{BASE_URL}/chat/completions").mock(
            side_effect=[_completion(json.dumps(verdicts))]
        )
        client = _client()
        try:
            kept, notes = await vet_analogs(client, "Taksit kalemi", cards)
        finally:
            await client.aclose()
        assert [card.brd_ref for card in kept] == ["BRD-a", "BRD-b"]
        assert len(notes) == 1, "a verdict for an analog that was never presented was honored"
        assert "medyandan çıkarıldı" in notes[0].text
        assert "veri migrasyonu" in notes[0].text
        assert "BRD-poison" in notes[0].text

    @respx.mock
    async def test_an_unusable_reply_keeps_the_full_set(self) -> None:
        cards = [_card("a", 10.0), _card("b", 11.0)]
        respx.post(f"{BASE_URL}/chat/completions").mock(
            side_effect=[_completion("I refuse to answer in JSON")]
        )
        client = _client()
        try:
            kept, notes = await vet_analogs(client, "Taksit kalemi", cards)
        finally:
            await client.aclose()
        assert kept == cards and notes == []

    @respx.mock
    async def test_a_dead_gateway_keeps_the_full_set(self) -> None:
        cards = [_card("a", 10.0), _card("b", 11.0)]
        respx.post(f"{BASE_URL}/chat/completions").mock(side_effect=httpx.ConnectError("refused"))
        client = _client()
        try:
            kept, notes = await vet_analogs(client, "Taksit kalemi", cards)
        finally:
            await client.aclose()
        assert kept == cards and notes == []


class TestNoAnalogProposal:
    @respx.mock
    async def test_a_valid_proposal_is_cone_widened(self) -> None:
        respx.post(f"{BASE_URL}/chat/completions").mock(
            side_effect=[
                _completion(
                    '{"optimistic": 4, "likely": 5, "pessimistic": 6, '
                    '"rationale": "yeni modül", "assumptions": ["API hazır varsayıldı"]}'
                )
            ]
        )
        client = _client()
        try:
            proposal = await propose_no_analog_band(
                client, "Yeni modül", "billing-core dokunulacak", ConeStage.CONCEPT
            )
        finally:
            await client.aclose()
        assert proposal is not None
        band, rationale, assumptions = proposal
        assert band.pessimistic == 20.0, "the cone floor was not enforced"
        assert rationale == "yeni modül"
        assert assumptions and "API hazır" in assumptions[0].text

    @respx.mock
    async def test_disordered_or_garbage_proposals_fall_back(self) -> None:
        client = _client()
        route = respx.post(f"{BASE_URL}/chat/completions")
        try:
            route.mock(
                side_effect=[_completion('{"optimistic": 9, "likely": 5, "pessimistic": 6}')]
            )
            assert await propose_no_analog_band(client, "x", "", ConeStage.CONCEPT) is None
            route.mock(side_effect=[_completion("not json at all")])
            assert await propose_no_analog_band(client, "x", "", ConeStage.CONCEPT) is None
        finally:
            await client.aclose()


class TestAnalogContext:
    def test_cards_render_and_empty_stays_empty(self) -> None:
        text = analog_context([_card("a", 10.0)])
        assert "Analog a" in text and "actual=10.0 pd" in text
        assert analog_context([]) == ""


@pytest.mark.db
class TestEstimatorWiring:
    """The call sites, proven against the real estimator."""

    @respx.mock
    async def test_no_analog_lines_carry_the_model_proposed_band(
        self, session: AsyncSession, clean_tables: None
    ) -> None:
        # EMPTY ledger: every work item takes the no-analog branch.
        def responder(request: httpx.Request) -> httpx.Response:
            body = request.content.decode("utf-8")
            if "ESTIMO-IMPACT-PROTOCOL" in body:
                return _completion(
                    '{"action": "finalize", "analysis": {"modules": [], "confidence": "low"}}'
                )
            if "ESTIMO-PROPOSE" in body:
                return _completion('{"optimistic": 2, "likely": 5, "pessimistic": 20}')
            return _completion("irrelevant")

        respx.post(f"{BASE_URL}/chat/completions").mock(side_effect=responder)
        respx.post(f"{BASE_URL}/embeddings").mock(
            return_value=httpx.Response(
                200,
                json={
                    "object": "list",
                    "model": "m",
                    "data": [{"object": "embedding", "index": 0, "embedding": [0.1] * 8}],
                    "usage": {"prompt_tokens": 1, "total_tokens": 1},
                },
            )
        )
        state = await run_brd(FIXTURES / "BRD-AUR-26-02-konsolide-fatura.docx")
        client = _client()
        try:
            boe = await estimate_state(session, state, client=client)
        finally:
            await client.aclose()
        assert boe.lines
        for line in boe.lines:
            assert line.basis_note is not None
            assert line.basis_note.startswith(MODEL_PROPOSED_BASIS)
            assert line.range == ThreePoint(optimistic=2.0, likely=5.0, pessimistic=20.0)
            assert any(ref.uri == "note://model-proposal" for ref in line.evidence)

    @respx.mock
    async def test_vetting_runs_before_the_band(
        self, session: AsyncSession, clean_tables: None
    ) -> None:
        report = await import_seed(session, SEED)
        assert report.rejected == []

        def responder(request: httpx.Request) -> httpx.Response:
            body = request.content.decode("utf-8")
            if "ESTIMO-VET" in body:
                match = re.search(r"id=([0-9a-f-]{36})", body)
                assert match is not None
                verdict = {
                    "verdicts": [
                        {
                            "entry_id": match.group(1),
                            "comparable": False,
                            "reason": "Test gerekçesi.",
                        }
                    ]
                }
                return _completion(json.dumps(verdict))
            if "ESTIMO-IMPACT-PROTOCOL" in body:
                return _completion(
                    '{"action": "finalize", "analysis": {"modules": [], "confidence": "low"}}'
                )
            return _completion("irrelevant")

        respx.post(f"{BASE_URL}/chat/completions").mock(side_effect=responder)
        respx.post(f"{BASE_URL}/embeddings").mock(
            return_value=httpx.Response(
                200,
                json={
                    "object": "list",
                    "model": "m",
                    "data": [{"object": "embedding", "index": 0, "embedding": [0.1] * 8}],
                    "usage": {"prompt_tokens": 1, "total_tokens": 1},
                },
            )
        )
        state = await run_brd(FIXTURES / "BRD-AUR-26-02-konsolide-fatura.docx")
        client = _client()
        try:
            boe = await estimate_state(session, state, client=client)
        finally:
            await client.aclose()
        vetted_notes = [
            assumption
            for line in boe.lines
            for assumption in line.assumptions
            if "medyandan çıkarıldı" in assumption.text
        ]
        assert vetted_notes, "no exclusion reached the assumption register"
        assert all("Test gerekçesi" in note.text for note in vetted_notes)
