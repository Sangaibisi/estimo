"""Gateway configuration. Environment is the only config source (AGENTS §2.9)."""

from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class GatewayConfig(BaseModel):
    """Connection + routing config for the OpenAI-compatible gateway.

    `profiles` maps pipeline stage names to model names configured on the gateway
    (named profiles only — model names never appear in code). A "default" entry is the
    fallback for stages without an explicit profile.
    """

    base_url: HttpUrl
    api_key: SecretStr
    max_retries: int = Field(default=2, ge=0, le=10)
    timeout_seconds: float = Field(default=120.0, gt=0)
    connect_timeout_seconds: float = Field(default=5.0, gt=0)
    profiles: dict[str, str] = Field(default_factory=dict)

    def model_for_stage(self, stage: str) -> str | None:
        return self.profiles.get(stage) or self.profiles.get("default")


class GatewaySettings(BaseSettings, GatewayConfig):
    """Standalone loader (`ESTIMO_GATEWAY__*`) for tools like the smoke check.

    The api embeds `GatewayConfig` in its own Settings instead; both read the exact
    same environment variable names.
    """

    model_config = SettingsConfigDict(
        env_prefix="ESTIMO_GATEWAY__",
        extra="ignore",
    )
