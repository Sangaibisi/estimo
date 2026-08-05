"""The panel-override SQL against a real schema.

The fake-engine tests in packages/gateway prove the merge; this one proves the
actual query — table name, key literal, JSONB shape — against the migrated
database, because a typo there degrades silently to "env only" and every CLI
would again ignore the Admin panel.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from estimo_gateway import deployment_gateway_config

pytestmark = pytest.mark.db

_ENV_KEYS = (
    "ESTIMO_GATEWAY__BASE_URL",
    "ESTIMO_GATEWAY__API_KEY",
    "ESTIMO_GATEWAY__PROFILES",
    "ESTIMO_SECRET_KEY",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


async def test_a_panel_saved_gateway_is_read_from_the_real_table(
    engine: AsyncEngine,
) -> None:
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM runtime_settings WHERE key = 'gateway'"))
        await connection.execute(
            text(
                "INSERT INTO runtime_settings (key, value) VALUES ('gateway', "
                '\'{"base_url": "http://panel-gw.invalid/v1", '
                '"api_key": "plain:sk-panel", '
                '"profiles": {"default": "panel-model"}}\'::jsonb)'
            )
        )
    try:
        config = await deployment_gateway_config(engine)
        assert config is not None
        assert str(config.base_url) == "http://panel-gw.invalid/v1"
        assert config.api_key.get_secret_value() == "sk-panel"
        assert config.profiles == {"default": "panel-model"}
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM runtime_settings WHERE key = 'gateway'"))


async def test_an_empty_table_means_unconfigured_not_an_error(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM runtime_settings WHERE key = 'gateway'"))
    assert await deployment_gateway_config(engine) is None
