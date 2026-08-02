"""Workspace-level pytest wiring: skip db-marked tests when no database is provided."""

from __future__ import annotations

import os

import pytest

DB_ENV_VAR = "ESTIMO_TEST_DATABASE_URL"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get(DB_ENV_VAR):
        return
    skip_db = pytest.mark.skip(reason=f"{DB_ENV_VAR} not set")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip_db)
