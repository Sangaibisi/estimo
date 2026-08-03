"""runtime settings in the database + stored connection credentials (ADR-0008)

Operators standing Estimo up from source asked for the product to be configurable
from the product: gateway URL/key/profiles and connector credentials editable in
the Admin panel, with the environment demoted to bootstrap defaults. Secrets are
sealed before storage (estimo_core.secrets — Fernet when ESTIMO_SECRET_KEY is set,
a legible `plain:` prefix when not).

`runtime_settings` is deliberately GLOBAL (no tenant_id, no RLS): it holds
deployment-level infrastructure config — exactly the values `/v1/system` already
reports deployment-wide. The 0009 default privileges cover the app role's access.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runtime_settings",
        sa.Column("key", sa.String(60), primary_key=True),
        sa.Column("value", JSONB, nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    # Sealed credential stored on the connection itself — the panel alternative to
    # secret_env. Text, not String(n): Fernet tokens grow with the plaintext.
    op.add_column("connections", sa.Column("secret", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("connections", "secret")
    op.drop_table("runtime_settings")
