"""Discipline (FE/BE) slice key on the ledger (S13-3)

The maintainer's sharpened goal is person-days WITH a frontend/backend split. The
split's calibration data has to start accruing NOW: a nullable `discipline` column
on `ledger_entries`, fed by the actuals form, the seed importer and (eventually)
per-discipline product rows. Nullable with no backfill — a historical whole-item
row genuinely has no discipline, and inventing one would poison the very slices
this column exists to calibrate.

Not part of the generated `search_tsv` expression: discipline is a slice key, not
searchable text, and changing the generated column would rewrite the table.

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ledger_entries", sa.Column("discipline", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("ledger_entries", "discipline")
