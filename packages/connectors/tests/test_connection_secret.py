"""ADR-0008: credential resolution order for a connection's two lanes."""

from types import SimpleNamespace

import pytest
from estimo_connectors.base import connection_secret

from estimo_core.secrets import seal


def test_stored_secret_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The operator who typed a token into the panel expects THAT token to be used,
    even if a same-named env var lingers from an earlier env-lane setup."""
    monkeypatch.delenv("ESTIMO_SECRET_KEY", raising=False)
    monkeypatch.setenv("MY_TOKEN", "env-token")
    connection = SimpleNamespace(secret=seal("panel-token"), secret_env="MY_TOKEN")
    assert connection_secret(connection) == "panel-token"


def test_env_lane_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_TOKEN", "env-token")
    connection = SimpleNamespace(secret=None, secret_env="MY_TOKEN")
    assert connection_secret(connection) == "env-token"


def test_no_credential_is_none() -> None:
    assert connection_secret(SimpleNamespace(secret=None, secret_env=None)) is None


def test_missing_env_var_still_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GONE_TOKEN", raising=False)
    with pytest.raises(LookupError, match="GONE_TOKEN"):
        connection_secret(SimpleNamespace(secret=None, secret_env="GONE_TOKEN"))
