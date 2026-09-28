"""Base Pydantic schemas shared across domains. Skeleton.

Lives under models/ (not a separate schemas/ package) — request/response
contracts for a module sit alongside that module's ORM class in
models/<module>_models.py; see models/crm_models.py for the pattern.
"""
from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AuditOut(ORMModel):
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: str | None = None
    updated_by: str | None = None


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
