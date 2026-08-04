"""optimistic locking on the estimate row (S12-3 review)

`estimates.state` is one JSONB document that every workflow endpoint reads, mutates
in Python and writes back whole. With no lock and no version, two overlapping
requests both read the pre-image and the second write erases the first — both
callers get 200 and nothing is logged. A review reproduced it WITHOUT forcing any
interleaving: 11 of 12 natural races lost a write, and one user double-clicking a
button was enough, because the board's buttons did not disable during their request.

A version column makes every UPDATE carry `WHERE state_version = <read value>`, so
the loser fails loudly (409) instead of silently overwriting. This is cheaper and
broader than locking each endpoint: it covers writers that do not exist yet.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "estimates",
        sa.Column("state_version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("estimates", "state_version")
