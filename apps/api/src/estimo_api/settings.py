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
    # Optional owner/RLS-exempt URL for SYSTEM paths that must cross tenants: the
    # startup interrupted-run janitor and the webhook receiver's connection lookup.
    # Unset => those paths use the main connection (correct in single-tenant; in
    # multi-tenant they degrade to the app role's own-tenant view, documented).
    owner_database_url: PostgresDsn | None = None
    # OPTIONAL, and optional on purpose (ADR-0008): the model gateway is the one piece
    # of config an operator is most likely to get wrong at install time, and it is fully
    # manageable from Admin → Model gateway. Requiring it here meant a fresh deployment
    # could not BOOT without pasting an API key into a file — the opposite of what the
    # panel is for. Unset = the product runs deterministically (parsing, the ambiguity
    # gate, decomposition and calibrated bands all work) and every LLM-assisted step
    # degrades, visibly, until someone configures it in the panel.
    gateway: GatewayConfig | None = None

    @field_validator("gateway", mode="before")
    @classmethod
    def _tolerate_half_configured_gateway(cls, value: object) -> object:
        """A half-filled ESTIMO_GATEWAY__* block must not stop the process.

        pydantic builds the nested model from whichever sub-keys are present, so an
        `.env` carrying only `ESTIMO_GATEWAY__BASE_URL` (or only the key — the shape
        the commented escape hatch invites) raised a startup ValidationError. That is
        the worst possible failure for the one setting the Admin panel exists to fix:
        the process that owns the panel refuses to start. Treated as "not configured"
        instead, and the boot log says so.
        """
        if isinstance(value, dict) and not (value.get("base_url") and value.get("api_key")):
            return None
        return value

    # OIDC auth (ESTIMO_AUTH__ISSUER, …). Empty issuer => local accounts only.
    auth: AuthSettings = Field(default_factory=AuthSettings)
    # One-time token that authorizes creating the FIRST platform admin (S15-1).
    # Unset => the process generates one at boot and logs it, so an operator who
    # never set it can still finish setup from the container log — and nobody who
    # merely reaches the URL can.
    setup_token: str = ""
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
