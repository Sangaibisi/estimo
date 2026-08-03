"""SQLAlchemy models. Imported by Alembic autogenerate — keep import side-effect-free."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from estimo_knowledge.db import TenantScoped
from sqlalchemy import MetaData, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from estimo_core.models import SQL_NAMING_CONVENTION


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=SQL_NAMING_CONVENTION)


class Run(TenantScoped, Base):
    """One pipeline run record (estimation, import, index refresh, …)."""

    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30), default="created")
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
