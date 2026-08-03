"""LangGraph wiring: parse → gate → questions → [HITL interrupt] → decompose.

The graph checkpoints between nodes (MemorySaver) and interrupts after question
generation whenever blocked requirements exist; the CLI persists the pydantic state as
JSON so a human can answer offline and resume (S4-5). Answers feed BACK through the
gate — the gate re-evaluates; answers are never trusted blindly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from estimo_parse import parse_brd
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from pydantic import TypeAdapter

from estimo_gateway import GatewayClient
from estimo_pipeline.nodes import decompose, gate_requirements, generate_questions
from estimo_pipeline.state import PipelineState


def _parse_node(state: PipelineState) -> PipelineState:
    parsed = parse_brd(Path(state.source_path))
    return state.model_copy(update={"parsed": parsed, "status": "parsed"})


def build_graph(client: GatewayClient | None = None) -> Any:
    async def _gate(state: PipelineState) -> PipelineState:
        return await gate_requirements(state, client)

    async def _questions(state: PipelineState) -> PipelineState:
        return await generate_questions(state, client)

    async def _decompose(state: PipelineState) -> PipelineState:
        return await decompose(state, client)

    graph = StateGraph(PipelineState)
    graph.add_node("parse", _parse_node)
    graph.add_node("gate", _gate)
    graph.add_node("questions", _questions)
    graph.add_node("decompose", _decompose)
    graph.add_edge(START, "parse")
    graph.add_edge("parse", "gate")
    graph.add_edge("gate", "questions")
    graph.add_edge("questions", "decompose")
    graph.add_edge("decompose", END)
    return graph.compile(checkpointer=MemorySaver())


async def run_brd(
    path: Path, *, client: GatewayClient | None = None, thread_id: str = "cli"
) -> PipelineState:
    """Full pass over a BRD. If questions remain open the state says so — the caller
    collects answers and calls `resume_with_answers`."""
    compiled = build_graph(client)
    config = {"configurable": {"thread_id": thread_id}}
    result = await compiled.ainvoke(PipelineState(source_path=str(path)), config)
    return PipelineState.model_validate(result)


_ANSWERS_ADAPTER = TypeAdapter(dict[str, str])


async def resume_with_answers(
    state: PipelineState,
    answers: dict[str, str],
    *,
    client: GatewayClient | None = None,
) -> PipelineState:
    """Apply human answers and re-run gate → questions → decompose on the stored state.

    The answers payload is often hand-edited JSON: types are validated and unknown
    question ids rejected loudly instead of being silently dropped.
    """
    answers = _ANSWERS_ADAPTER.validate_python(answers)
    unknown = sorted(set(answers) - {q.id for q in state.questions})
    if unknown:
        msg = f"answers reference unknown question ids: {unknown}"
        raise ValueError(msg)
    merged = state.model_copy(update={"answers": {**state.answers, **answers}})
    regated = await gate_requirements(merged, client)
    questioned = await generate_questions(regated, client)
    return await decompose(questioned, client)
