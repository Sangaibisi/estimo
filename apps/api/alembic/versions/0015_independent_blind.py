"""Record whether an independent band was entered while the draft was still hidden

The anchoring telemetry's whole claim is that a band was recorded BEFORE its estimator
could see the AI number. The desk enforces that — but the draft has other doors: once
every line is signed, `GET /v1/estimates/{id}` returns the document and `/boe.docx`
exports it. Someone who read it there and then recorded a band was counted as
independent-first, indistinguishable from someone who did not.

So the fact is stored at the moment it is known, instead of being assumed later.
NULLABLE on purpose: rows written before this column existed were recorded without the
check, and back-filling `true` would be a claim about history nobody verified. NULL
means "not known", and the dashboard reports it as its own bucket rather than folding
it into the number it would flatter.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "independent_estimates",
        sa.Column("blind", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("independent_estimates", "blind")
