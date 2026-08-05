"""CLI: `estimo-embed` — give every un-embedded chunk and ledger row a vector.

The dense leg of hybrid retrieval matches on `embedding IS NOT NULL`, so until rows
carry vectors it contributes nothing and RRF fuses a single ranking. This is the
backfill that turns that on.

By default it is idempotent, selecting only rows whose embedding is NULL. After
switching embedding models you must pass `--refresh`: old rows keep their old vector,
which is not NULL, so a plain run skips them forever while the dimension filter keeps
them out of the dense leg — invisible to retrieval and invisible to a re-run.

Tenancy: the CLI uses whatever the connection can see. Run it with an owner-role URL to
cover every tenant, or pass `--tenant` to scope it to one under the RLS-bound app role,
where an unscoped connection would report "embedded 0 rows" for a corpus it simply
cannot see.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
from typing import Any

from pydantic import SecretStr
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from estimo_gateway import GatewayClient, GatewaySettings
from estimo_knowledge.embedding import DEFAULT_BATCH_SIZE, embed_pending


def _bind_tenant(session: Any, tenant: str) -> None:
    """Re-apply the tenant GUC on every transaction this session opens.

    `set_config(..., true)` is transaction-local, so a per-batch commit would drop it;
    the listener puts it back on each `after_begin`. The SET must be issued on the
    connection the event hands us — routing it through `session.execute` re-enters a
    session that is mid-provisioning and raises.
    """

    def _apply(_session: Any, _transaction: Any, connection: Any) -> None:
        connection.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"), {"tenant": tenant}
        )

    event.listen(session.sync_session, "after_begin", _apply)


async def _gateway_config(engine: Any) -> Any:
    """The gateway this deployment actually uses: the panel override first.

    The environment is only the bootstrap default (ADR-0008), and on a panel-managed
    deployment it is usually empty — so reading `GatewaySettings()` alone made the CLI
    report "gateway is not configured" about a deployment whose Admin screen showed a
    working one. The row is plain JSON in a global table; the seal is unwrapped with
    the same helper the API uses.
    """
    from sqlalchemy import text as _text

    from estimo_core.secrets import SealedSecretError, unseal
    from estimo_gateway import GatewayConfig

    stored: dict[str, Any] = {}
    try:
        async with engine.connect() as connection:
            row = await connection.execute(
                _text("SELECT value FROM runtime_settings WHERE key = 'gateway'")
            )
            found = row.first()
            stored = dict(found[0]) if found else {}
    except Exception:  # noqa: BLE001 - an old schema simply has no override
        stored = {}

    env: Any = None
    with contextlib.suppress(Exception):
        env = GatewaySettings()

    base_url = stored.get("base_url") or (str(env.base_url) if env else None)
    api_key: Any = env.api_key if env else None
    if stored.get("api_key"):
        try:
            api_key = SecretStr(unseal(stored["api_key"]))
        except SealedSecretError:
            pass
    if not base_url or api_key is None or not api_key.get_secret_value():
        return None
    profiles = stored.get("profiles") or (env.profiles if env else {})
    return GatewayConfig(base_url=base_url, api_key=api_key, profiles=profiles)


async def _run(batch_size: int, limit: int | None, refresh: bool, tenant: str | None) -> int:
    database_url = os.environ.get("ESTIMO_DATABASE_URL")
    if not database_url:
        print("error: ESTIMO_DATABASE_URL is not set", file=sys.stderr)
        return 2
    engine = create_async_engine(database_url)
    config = await _gateway_config(engine)
    if config is None:
        print(
            "error: no model gateway is configured — set it in Admin -> Model gateway "
            "(or ESTIMO_GATEWAY__*)",
            file=sys.stderr,
        )
        await engine.dispose()
        return 2
    client = GatewayClient(config)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            if tenant:
                # Under the NOSUPERUSER app role every table is RLS-guarded on this
                # GUC; without it the CLI sees nothing and cheerfully reports success.
                # Applied per transaction (embed_pending commits each batch), and set
                # here rather than imported from apps/api — a library package must not
                # depend on the application that uses it.
                _bind_tenant(session, tenant)
            report = await embed_pending(
                session, client, batch_size=batch_size, limit=limit, refresh=refresh
            )
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
        "--refresh",
        action="store_true",
        help="re-embed rows that already have a vector (required after a model switch)",
    )
    parser.add_argument(
        "--tenant",
        default=None,
        help="tenant UUID to scope to; required when connecting as the RLS-bound app role",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="stop after this many rows per table (for a metered first run)",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args.batch_size, args.limit, args.refresh, args.tenant)))
