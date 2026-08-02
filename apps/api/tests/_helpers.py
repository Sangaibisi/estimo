"""Shared test helpers for the api test suite."""

from __future__ import annotations

from pydantic import SecretStr

from estimo_api.settings import Settings
from estimo_gateway import GatewayConfig


def make_settings(database_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        gateway=GatewayConfig(
            base_url="http://mock-llm.invalid/v1",
            api_key=SecretStr("sk-test"),
            profiles={"default": "mock-small"},
        ),
    )
