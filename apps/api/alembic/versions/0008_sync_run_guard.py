"""sync-run concurrency guard: one running sync per connection

S9 review fix: the "is a sync already running" check raced the background start,
and the webhook path skipped it entirely. A partial unique index turns the second
concurrent start into an IntegrityError inside `run_sync` itself, so every entry
point inherits the guarantee.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Any run left 'running' by a crashed process would violate the new index's
    # intent and block future syncs; sweep before creating it.
    op.execute(
        "UPDATE sync_runs SET status = 'failed', "
        "error = 'interrupted (marked during 0008 migration)', finished_at = now() "
        "WHERE status = 'running'"
    )
    op.create_index(
        "uq_sync_runs_one_running",
        "sync_runs",
        ["connection_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )


def downgrade() -> None:
    op.drop_index("uq_sync_runs_one_running", table_name="sync_runs")
