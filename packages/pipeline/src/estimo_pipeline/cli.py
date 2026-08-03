"""CLI: run a BRD through the pipeline; answer questions offline; resume.

estimo-pipeline run fixtures/brd/BRD-….docx --state state.json
# edit state.json answers: {"Q-REQ-G-04": "…"}  (or provide --answers file)
estimo-pipeline resume state.json --answers answers.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from estimo_gateway import GatewayClient, GatewaySettings
from estimo_pipeline.graph import resume_with_answers, run_brd
from estimo_pipeline.state import PipelineState


def _client_from_env() -> GatewayClient | None:
    """Use the configured gateway when present; the offline deterministic floor
    otherwise. This makes the LLM blend live in the shipped entry point."""
    if not os.environ.get("ESTIMO_GATEWAY__BASE_URL"):
        return None
    return GatewayClient(GatewaySettings())


def _print_summary(state: PipelineState) -> None:
    print(f"status: {state.status}")
    print(f"requirements: {len(state.requirements)}  blocked: {len(state.blocked_ids)}")
    for question in state.questions:
        answered = "answered" if question.id in state.answers else "OPEN"
        print(f"  [{answered}] {question.id}: {question.question}")
    print(f"work items: {len(state.work_items)}  unmapped: {len(state.unmapped_ids)}")


async def _run(args: argparse.Namespace) -> int:
    client = _client_from_env()
    try:
        state = await run_brd(args.path, client=client)
    finally:
        if client is not None:
            await client.aclose()
    args.state.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    _print_summary(state)
    return 0


async def _resume(args: argparse.Namespace) -> int:
    state = PipelineState.model_validate_json(args.state.read_text(encoding="utf-8"))
    answers: dict[str, str] = {}
    if args.answers is not None:
        answers = json.loads(args.answers.read_text(encoding="utf-8"))
    client = _client_from_env()
    try:
        state = await resume_with_answers(state, answers, client=client)
    finally:
        if client is not None:
            await client.aclose()
    args.state.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    _print_summary(state)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="estimo-pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Parse + gate + questions + decompose a BRD")
    run_p.add_argument("path", type=Path)
    run_p.add_argument("--state", type=Path, default=Path("estimo-state.json"))

    resume_p = sub.add_parser("resume", help="Apply answers and re-run the gate")
    resume_p.add_argument("state", type=Path)
    resume_p.add_argument("--answers", type=Path)

    args = parser.parse_args()
    if args.command == "run" and not args.path.exists():
        parser.error(f"file not found: {args.path}")
    handler = _run if args.command == "run" else _resume
    sys.exit(asyncio.run(handler(args)))


if __name__ == "__main__":
    main()
