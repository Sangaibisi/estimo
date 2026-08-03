"""estimator rationale on the independent band (S12-1)

The design captures an optional rationale line at entry time ("Scheduler is well
covered by tests; the fee matrix is the unknown, so P stays wide.") and shows it in
the revealed row. It is the only record of WHY a band was what it was — the delta to
the AI draft says how far apart they were, never what the human knew.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("independent_estimates", sa.Column("rationale", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("independent_estimates", "rationale")
