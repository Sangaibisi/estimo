"""estimate workflow: estimates, independent estimates, signatures, ui events

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "estimates",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("brd_ref", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("state", JSONB, nullable=False),
        sa.Column("boe", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_estimates")),
    )
    op.create_table(
        "independent_estimates",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("estimate_id", UUID(as_uuid=True), nullable=False),
        sa.Column("work_item_id", sa.String(length=120), nullable=False),
        sa.Column("estimator", sa.String(length=120), nullable=False),
        sa.Column("optimistic", sa.Numeric(8, 2), nullable=False),
        sa.Column("likely", sa.Numeric(8, 2), nullable=False),
        sa.Column("pessimistic", sa.Numeric(8, 2), nullable=False),
        sa.Column("revealed", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_independent_estimates")),
        sa.ForeignKeyConstraint(
            ["estimate_id"],
            ["estimates.id"],
            name=op.f("fk_independent_estimates_estimate_id_estimates"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "estimate_id",
            "work_item_id",
            "estimator",
            name="uq_independent_estimates_item_estimator",
        ),
    )
    op.create_table(
        "line_signatures",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("estimate_id", UUID(as_uuid=True), nullable=False),
        sa.Column("work_item_id", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("role", sa.String(length=80), nullable=False),
        sa.Column(
            "signed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_line_signatures")),
        sa.ForeignKeyConstraint(
            ["estimate_id"],
            ["estimates.id"],
            name=op.f("fk_line_signatures_estimate_id_estimates"),
            ondelete="CASCADE",
        ),
    )
    op.create_table(
        "ui_events",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("estimate_id", UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(length=60), nullable=False),
        sa.Column("payload", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ui_events")),
        sa.ForeignKeyConstraint(
            ["estimate_id"],
            ["estimates.id"],
            name=op.f("fk_ui_events_estimate_id_estimates"),
            ondelete="SET NULL",
        ),
    )


def downgrade() -> None:
    op.drop_table("ui_events")
    op.drop_table("line_signatures")
    op.drop_table("independent_estimates")
    op.drop_table("estimates")
