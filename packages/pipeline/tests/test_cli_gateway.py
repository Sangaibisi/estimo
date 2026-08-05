"""The pipeline CLI resolves its gateway through the DEPLOYMENT, not just env.

Wiring regression guard: reverting `_resolve_client` to the old env-only read
makes both tests fail — the first because the shared helper is never consulted,
the second because the DB engine is never built.
"""

from __future__ import annotations

from typing import Any

import pytest
from estimo_pipeline import cli


async def test_the_cli_consults_the_deployment_gateway_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ESTIMO_DATABASE_URL", raising=False)
    seen: list[Any] = []

    async def _recorder(engine: Any) -> None:
        seen.append(engine)

    monkeypatch.setattr(cli, "deployment_gateway_client", _recorder)
    assert await cli._resolve_client() is None
    # No database on a laptop run: the helper still runs, in pure-env mode.
    assert seen == [None]


async def test_a_database_url_makes_the_cli_read_the_panel_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "ESTIMO_DATABASE_URL", "postgresql+asyncpg://estimo:estimo@db.invalid/estimo"
    )
    seen: list[Any] = []

    async def _recorder(engine: Any) -> None:
        seen.append(engine)

    monkeypatch.setattr(cli, "deployment_gateway_client", _recorder)
    assert await cli._resolve_client() is None
    assert len(seen) == 1
    # create_async_engine is lazy, so no connection is attempted here — but the
    # engine must exist, or a panel-configured deployment is invisible to the CLI.
    assert seen[0] is not None
