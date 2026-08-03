"""calibration loop: ledger provenance, analog feedback, calibration snapshots

S8-1/S8-2: rows the product writes into the ledger carry an origin_ref
("estimate://{id}/{work_item_id}"), analogs receive outcome feedback that folds
into ranking, and every recorded actual snapshots the calibration state for the
drift dashboard.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ledger_entries", sa.Column("origin_ref", sa.String(length=200), nullable=True))
    op.create_index("uq_ledger_entries_origin_ref", "ledger_entries", ["origin_ref"], unique=True)
    op.create_table(
        "analog_feedback",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("entry_id", UUID(as_uuid=True), nullable=False),
        sa.Column("origin_ref", sa.String(length=200), nullable=False),
        sa.Column("weight", sa.Numeric(6, 3), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analog_feedback")),
        sa.ForeignKeyConstraint(
            ["entry_id"],
            ["ledger_entries.id"],
            name=op.f("fk_analog_feedback_entry_id_ledger_entries"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "uq_analog_feedback_entry_origin",
        "analog_feedback",
        ["entry_id", "origin_ref"],
        unique=True,
    )
    op.create_table(
        "calibration_snapshots",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("samples", sa.Integer(), nullable=False),
        sa.Column("prior_based", sa.Boolean(), nullable=False),
        sa.Column("q10", sa.Numeric(8, 3), nullable=False),
        sa.Column("q50", sa.Numeric(8, 3), nullable=False),
        sa.Column("q90", sa.Numeric(8, 3), nullable=False),
        sa.Column("nominal", sa.Numeric(4, 2), nullable=False),
        sa.Column("rolling_coverage", sa.Numeric(4, 3), nullable=True),
        sa.Column("trigger", sa.String(length=60), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calibration_snapshots")),
    )


def downgrade() -> None:
    op.drop_table("calibration_snapshots")
    op.drop_index("uq_analog_feedback_entry_origin", table_name="analog_feedback")
    op.drop_table("analog_feedback")
    op.drop_index("uq_ledger_entries_origin_ref", table_name="ledger_entries")
    op.drop_column("ledger_entries", "origin_ref")
