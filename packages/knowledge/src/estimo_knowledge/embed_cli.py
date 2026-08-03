"""CLI: `estimo-embed` — give every un-embedded chunk and ledger row a vector.

The dense leg of hybrid retrieval matches on `embedding IS NOT NULL`, so until rows
carry vectors it contributes nothing and RRF fuses a single ranking. This is the
backfill that turns that on, and the command to re-run after switching embedders
(rows keep their old model id and dimension, so they simply drop out of the dense leg
until re-embedded — never mixed into the wrong vector space).

Idempotent: it only selects rows whose embedding is NULL.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from estimo_gateway import GatewayClient, GatewaySettings
from estimo_knowledge.embedding import DEFAULT_BATCH_SIZE, embed_pending


async def _run(batch_size: int, limit: int | None) -> int:
    database_url = os.environ.get("ESTIMO_DATABASE_URL")
    if not database_url:
        print("error: ESTIMO_DATABASE_URL is not set", file=sys.stderr)
        return 2
    try:
        config = GatewaySettings()
    except Exception as exc:  # noqa: BLE001 - surfaced as a message, not a traceback
        print(f"error: gateway is not configured ({exc})", file=sys.stderr)
        return 2

    engine = create_async_engine(database_url)
    client = GatewayClient(config)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            report = await embed_pending(session, client, batch_size=batch_size, limit=limit)
    finally:
        await client.aclose()
        await engine.dispose()

    print(
        f"embedded {report.embedded} rows"
        + (f" with {report.model} (dim {report.dimension})" if report.model else "")
        + (f", {report.truncated} truncated" if report.truncated else "")
        + (f", {report.failed_batches} batches FAILED" if report.failed_batches else "")
    )
    # A partial run is a real outcome, not a success: the operator needs a non-zero
    # exit to notice that part of the corpus is still invisible to the dense leg.
    return 0 if report.ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="estimo-embed",
        description="Embed chunks and ledger rows that have no vector yet.",
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="stop after this many rows per table (for a metered first run)",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args.batch_size, args.limit)))
