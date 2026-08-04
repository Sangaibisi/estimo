"""Store the rolling-coverage sample count next to the rolling-coverage rate

`calibration_snapshots.samples` is the TRANSFER-DISTRIBUTION count — every completed
ledger row of any origin. `rolling_coverage` is a different measurement over a
different population: at most `ROLLING_WINDOW` rows, product-estimated, banded. The
dashboard's tooltip paired the first count with the second rate, so a 3-row 33%
coverage rendered as "33% · n=33".

NULLABLE with no backfill: nobody can recover how many rows a snapshot written last
month was computed from, and inventing one is exactly the kind of number this screen
exists not to print. Historical points show their rate without a count.

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "calibration_snapshots",
        sa.Column("rolling_samples", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("calibration_snapshots", "rolling_samples")
