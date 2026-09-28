"""Models for the Projects module (§1/§7 of the API spec) — Projects + SOW
rollups.

Full ORM schema implemented (the central "database logic" every developer
builds their service/route layer on top of) — business logic itself (created
from a WON opportunity, target_end_date >= start_date, delete blocked by
active SOWs) is NOT here; see services/project_service.py for what still
needs to be written, and repositories/project_repository.py for the
ready-to-use data-access classes.

Tables owned: project, project_status (lookup).
"""
import uuid
from datetime import date

from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Date, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import AuditMixin, Base, SoftDeleteMixin
from src.models.common import AuditOut
from src.models.contracts_models import AgreementOut
from src.models.delivery_models import SowDetailOut


class ProjectStatus(Base):
    __tablename__ = "project_status"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    is_terminal: Mapped[bool] = mapped_column(Boolean, default=False)


class Project(Base, AuditMixin, SoftDeleteMixin):
    __tablename__ = "project"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # e.g. PRJ-00017
    account_id: Mapped[str] = mapped_column(ForeignKey("account.id"))
    opportunity_id: Mapped[str | None] = mapped_column(ForeignKey("opportunity.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    project_status_id: Mapped[int] = mapped_column(ForeignKey("project_status.id"))
    account_executive_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True)
    start_date: Mapped[date] = mapped_column(Date)
    target_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    account: Mapped["Account"] = relationship()  # noqa: F821 (crm_models.Account)
    opportunity: Mapped["Opportunity | None"] = relationship()  # noqa: F821 (crm_models.Opportunity)
    status: Mapped["ProjectStatus"] = relationship()


# --- request/response (Pydantic) schemas ------------------------------------


class ProjectCreate(BaseModel):
    opportunity_id: str = Field(description="must be a WON opportunity")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    account_executive_employee_id: uuid.UUID | None = None
    start_date: date
    target_end_date: date | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, description="project_status lookup code")
    account_executive_employee_id: uuid.UUID | None = None
    target_end_date: date | None = None
    actual_end_date: date | None = None


class ProjectOut(AuditOut):
    id: str
    account_id: str
    opportunity_id: str | None = None
    name: str
    description: str | None = None
    status: str
    account_executive_employee_id: uuid.UUID | None = None
    start_date: date
    target_end_date: date | None = None
    actual_end_date: date | None = None


class ProjectSowCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    governing_msa_id: str
    effective_date: date | None = None
    expiry_date: date | None = None
    billing_model: str | None = Field(default=None, max_length=30)
    total_value: float | None = None
    currency: str = Field(default="USD", max_length=3)
    headcount: int | None = None
    invoicing_frequency: str | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=2000)


class ProjectSowOut(BaseModel):
    agreement: AgreementOut
    sow_detail: SowDetailOut
