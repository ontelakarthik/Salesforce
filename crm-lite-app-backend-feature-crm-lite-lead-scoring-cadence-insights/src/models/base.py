"""Declarative base + audit / soft-delete mixins (project convention:
every entity has ownership, timestamps, soft delete). Skeleton."""
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AuditMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
