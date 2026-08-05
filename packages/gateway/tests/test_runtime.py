"""The deployment gateway helper: panel override first, env as bootstrap (ADR-0008).

These are the CLI-facing semantics. The API's own precedence tests live in
apps/api/tests/test_system.py; `merge_gateway` is one shared implementation, so what
is asserted here is the parts a CLI can get wrong on its own: the DB read, the
missing-table degradation, and the per-field merge details the first copy of this
helper silently dropped (timeouts, cleared profiles, unseal-failure logging).
"""

from __future__ import annotations

from typing import Any, Self

import pytest
from pydantic import SecretStr

from estimo_gateway import (
    GatewayConfig,
    deployment_gateway_client,
    deployment_gateway_config,
    merge_gateway,
    stored_gateway_override,
)

_ENV_KEYS = (
    "ESTIMO_GATEWAY__BASE_URL",
    "ESTIMO_GATEWAY__API_KEY",
    "ESTIMO_GATEWAY__PROFILES",
    "ESTIMO_GATEWAY__TIMEOUT_SECONDS",
    "ESTIMO_GATEWAY__CONNECT_TIMEOUT_SECONDS",
    "ESTIMO_GATEWAY__MAX_RETRIES",
    "ESTIMO_SECRET_KEY",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


class _FakeResult:
    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self._row = row

    def first(self) -> tuple[Any, ...] | None:
        return self._row


class _FakeConnection:
    def __init__(self, value: dict[str, Any] | None) -> None:
        self._value = value

    async def exec_driver_sql(self, sql: str) -> _FakeResult:
        assert "runtime_settings" in sql
        return _FakeResult((self._value,) if self._value is not None else None)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakeEngine:
    def __init__(self, value: dict[str, Any] | None) -> None:
        self._value = value

    def connect(self) -> _FakeConnection:
        return _FakeConnection(self._value)


class _BrokenEngine:
    """A pre-0011 schema: connecting works, the table does not exist."""

    def connect(self) -> _FakeConnection:
        raise RuntimeError("relation runtime_settings does not exist")


class TestMergeGateway:
    def test_the_panel_alone_is_a_complete_configuration(self) -> None:
        config = merge_gateway(
            None, {"base_url": "http://gw.invalid/v1", "api_key": "plain:sk-panel"}
        )
        assert config is not None
        assert str(config.base_url) == "http://gw.invalid/v1"
        assert config.api_key.get_secret_value() == "sk-panel"

    def test_panel_fields_override_env_per_field(self) -> None:
        env = GatewayConfig(
            base_url="http://env.invalid/v1",
            api_key=SecretStr("sk-env"),
            profiles={"default": "env-model"},
        )
        config = merge_gateway(env, {"base_url": "http://panel.invalid/v1"})
        assert config is not None
        assert str(config.base_url) == "http://panel.invalid/v1"
        assert config.api_key.get_secret_value() == "sk-env"
        assert config.profiles == {"default": "env-model"}

    def test_panel_timeouts_and_retries_are_carried(self) -> None:
        # The first CLI copy of this helper dropped these three fields, so a
        # panel-tuned timeout silently reverted to the default on every CLI run.
        config = merge_gateway(
            None,
            {
                "base_url": "http://gw.invalid/v1",
                "api_key": "plain:sk",
                "timeout_seconds": 75.0,
                "connect_timeout_seconds": 2.0,
                "max_retries": 0,
            },
        )
        assert config is not None
        assert config.timeout_seconds == 75.0
        assert config.connect_timeout_seconds == 2.0
        assert config.max_retries == 0

    def test_deliberately_cleared_profiles_stay_cleared(self) -> None:
        env = GatewayConfig(
            base_url="http://env.invalid/v1",
            api_key=SecretStr("sk-env"),
            profiles={"default": "env-model"},
        )
        config = merge_gateway(env, {"base_url": "http://env.invalid/v1", "profiles": {}})
        assert config is not None
        assert config.profiles == {}

    def test_an_unsealable_stored_key_degrades_to_the_env_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ESTIMO_SECRET_KEY", "a-master-key")
        env = GatewayConfig(base_url="http://env.invalid/v1", api_key=SecretStr("sk-env"))
        config = merge_gateway(env, {"api_key": "enc:not-really-fernet"})
        assert config is not None
        assert config.api_key.get_secret_value() == "sk-env"

    def test_an_empty_env_key_is_not_a_configured_gateway(self) -> None:
        env = GatewayConfig(base_url="http://env.invalid/v1", api_key=SecretStr(""))
        assert merge_gateway(env, None) is None
        assert merge_gateway(env, {"base_url": "http://panel.invalid/v1"}) is None


class TestDeploymentGatewayConfig:
    async def test_panel_only_deployment_with_empty_environment(self) -> None:
        engine = _FakeEngine({"base_url": "http://panel.invalid/v1", "api_key": "plain:sk-panel"})
        config = await deployment_gateway_config(engine)
        assert config is not None
        assert str(config.base_url) == "http://panel.invalid/v1"

    async def test_no_engine_falls_back_to_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ESTIMO_GATEWAY__BASE_URL", "http://env.invalid/v1")
        monkeypatch.setenv("ESTIMO_GATEWAY__API_KEY", "sk-env")
        config = await deployment_gateway_config(None)
        assert config is not None
        assert str(config.base_url) == "http://env.invalid/v1"

    async def test_nothing_configured_anywhere_is_none_not_an_error(self) -> None:
        assert await deployment_gateway_config(_FakeEngine(None)) is None
        assert await deployment_gateway_config(None) is None

    async def test_a_schema_without_the_table_degrades_to_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ESTIMO_GATEWAY__BASE_URL", "http://env.invalid/v1")
        monkeypatch.setenv("ESTIMO_GATEWAY__API_KEY", "sk-env")
        config = await deployment_gateway_config(_BrokenEngine())
        assert config is not None
        assert config.api_key.get_secret_value() == "sk-env"

    async def test_stored_override_reads_the_gateway_row(self) -> None:
        override = await stored_gateway_override(_FakeEngine({"base_url": "http://x/v1"}))
        assert override == {"base_url": "http://x/v1"}
        assert await stored_gateway_override(_FakeEngine(None)) is None

    async def test_client_helper_builds_a_client_only_when_configured(self) -> None:
        client = await deployment_gateway_client(
            _FakeEngine({"base_url": "http://panel.invalid/v1", "api_key": "plain:sk"})
        )
        assert client is not None
        await client.aclose()
        assert await deployment_gateway_client(_FakeEngine(None)) is None
