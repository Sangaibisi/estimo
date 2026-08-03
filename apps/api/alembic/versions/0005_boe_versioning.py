"""boe versioning: draft version stamps + persisted critic findings

S7 review fix: independent estimates and line signatures are bound to the draft
version they were recorded against, so a rebuilt BoE never inherits reveals or
sign-offs from a dead draft. Critic findings persist with the record instead of
living only in the build response.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "estimates",
        sa.Column("boe_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("estimates", sa.Column("critic", JSONB, nullable=True))
    op.add_column(
        "independent_estimates",
        sa.Column("boe_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "line_signatures",
        sa.Column("boe_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.drop_constraint(
        "uq_independent_estimates_item_estimator", "independent_estimates", type_="unique"
    )
    op.create_unique_constraint(
        "uq_independent_estimates_item_estimator_version",
        "independent_estimates",
        ["estimate_id", "work_item_id", "estimator", "boe_version"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_independent_estimates_item_estimator_version",
        "independent_estimates",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_independent_estimates_item_estimator",
        "independent_estimates",
        ["estimate_id", "work_item_id", "estimator"],
    )
    op.drop_column("line_signatures", "boe_version")
    op.drop_column("independent_estimates", "boe_version")
    op.drop_column("estimates", "critic")
    op.drop_column("estimates", "boe_version")
