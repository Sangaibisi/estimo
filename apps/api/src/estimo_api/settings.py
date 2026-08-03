"""API settings. Environment is the only config source (AGENTS §2.9, ADR-0006)."""

from __future__ import annotations

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from estimo_api.auth import AuthSettings
from estimo_gateway import GatewayConfig


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ESTIMO_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    database_url: PostgresDsn
    gateway: GatewayConfig
    # OIDC auth (ESTIMO_AUTH__ISSUER, …). Empty issuer => single-tenant open mode.
    auth: AuthSettings = Field(default_factory=AuthSettings)
    log_level: str = "INFO"
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    @field_validator("database_url")
    @classmethod
    def _asyncpg_scheme(cls, value: PostgresDsn) -> PostgresDsn:
        if value.scheme != "postgresql+asyncpg":
            msg = f"database_url scheme must be postgresql+asyncpg, got {value.scheme!r}"
            raise ValueError(msg)
        return value
