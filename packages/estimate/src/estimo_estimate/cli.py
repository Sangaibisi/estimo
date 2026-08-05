"""CLI: `estimo-boe <state.json> --docx boe.docx` — estimation-ready state → BoE draft."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from estimo_code import CodeGraph
from estimo_pipeline import PipelineState
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from estimo_estimate.boe_render import render_boe_docx
from estimo_estimate.critic import review_boe
from estimo_estimate.estimator import estimate_state
from estimo_gateway import deployment_gateway_client


async def _stored_graphs(session: AsyncSession) -> list[CodeGraph]:
    """Persisted per-repo graphs (S13-2), via plain SQL.

    Deliberately not `estimo_connectors.graphstore`: the estimation package must not
    depend on the connector layer for one SELECT. A schema without the table (pre-
    0017) is a deployment without graphs, not an error."""
    try:
        rows = await session.execute(text("SELECT payload FROM code_graphs ORDER BY repo"))
    except Exception:  # noqa: BLE001
        await session.rollback()
        return []
    graphs: list[CodeGraph] = []
    for (payload,) in rows:
        try:
            graphs.append(CodeGraph.from_payload(payload))
        except (KeyError, TypeError, ValueError):
            continue
    return graphs


async def _run(args: argparse.Namespace) -> int:
    database_url = os.environ.get("ESTIMO_DATABASE_URL")
    if not database_url:
        print("error: ESTIMO_DATABASE_URL is not set", file=sys.stderr)
        return 2
    state = PipelineState.model_validate_json(args.state.read_text(encoding="utf-8"))

    graph = None
    if args.repo is not None:
        graph = CodeGraph.build(args.repo, repo=args.repo.name)

    engine = create_async_engine(database_url)
    # Panel override first, env as bootstrap (ADR-0008): on a panel-configured
    # deployment this CLI must reach the same model the Admin screen shows.
    client = await deployment_gateway_client(engine)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            stored = await _stored_graphs(session)
            boe = await estimate_state(session, state, graph=graph, graphs=stored, client=client)
    finally:
        await engine.dispose()
        if client is not None:
            await client.aclose()

    findings = review_boe(boe, state)
    if args.json is not None:
        args.json.write_text(boe.model_dump_json(indent=2), encoding="utf-8")
    if args.docx is not None:
        render_boe_docx(boe, args.docx)

    total = boe.total
    print(f"BoE {boe.brd_ref}: {len(boe.lines)} lines")
    print(f"total: {total.optimistic} / {total.likely} / {total.pessimistic} pd")
    for finding in findings:
        print(f"CRITIC: {finding}")
    return 1 if any("GATE LEAK" in finding for finding in findings) else 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="estimo-boe")
    parser.add_argument("state", type=Path)
    parser.add_argument("--repo", type=Path, help="Code repo root for impact evidence")
    parser.add_argument("--json", type=Path)
    parser.add_argument("--docx", type=Path)
    args = parser.parse_args()
    if not args.state.exists():
        parser.error(f"file not found: {args.state}")
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
