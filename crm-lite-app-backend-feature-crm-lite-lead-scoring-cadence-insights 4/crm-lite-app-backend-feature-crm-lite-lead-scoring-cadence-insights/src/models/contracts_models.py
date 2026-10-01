"""Models for the Contracts module (§1/§8 of the API spec) — Agreements
(NDA/MSA/SOW core: create, sign, supersede, clauses, documents, reviews).

Full ORM schema implemented (the central "database logic" every developer
builds their service/route layer on top of) — business logic itself (status
machine, sign/supersede rules, SLA timers) is NOT here; see
services/contracts_service.py for what still needs to be written, and
repositories/contracts_repository.py for the ready-to-use data-access classes.

Tables owned: agreement_type (lookup), agreement_status (lookup), agreement,
agreement_document, agreement_clause, agreement_review.
SOW-specific sub-resources (sow_detail, sow_budget, ...) live in
models/delivery_models.py since Delivery is a separate service per the API
spec, even though a SOW is itself an agreement row (type=SOW) here.
"""
import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import AuditMixin, Base, SoftDeleteMixin
from src.models.common import AuditOut

# --- lookups -----------------------------------------------------------------


class AgreementType(Base):
    __tablename__ = "agreement_type"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    default_sla_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AgreementStatus(Base):
    __tablename__ = "agreement_status"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    is_terminal: Mapped[bool] = mapped_column(Boolean, default=False)


# --- core entities -------------------------------------------------------------


class Agreement(Base, AuditMixin, SoftDeleteMixin):
    __tablename__ = "agreement"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # e.g. AGR-2026-SOW-00113
    account_id: Mapped[str] = mapped_column(ForeignKey("account.id"))
    agreement_type_id: Mapped[int] = mapped_column(ForeignKey("agreement_type.id"))
    agreement_status_id: Mapped[int] = mapped_column(ForeignKey("agreement_status.id"))
    title: Mapped[str] = mapped_column(String(255))
    initiated_by_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    signed_by_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True)
    supersedes_agreement_id: Mapped[str | None] = mapped_column(
        ForeignKey("agreement.id"), nullable=True)
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sla_breached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sharepoint_folder_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # Salesforce Contract fields with no existing equivalent — "Company
    # Signed By/Date" is already signed_by_employee_id/signed_at above, and
    # "Contract Number"/"Status" are already this row's own id/status FK.
    contract_term_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    owner_expiration_notice_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    customer_signed_contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contact.id"), nullable=True)
    customer_signed_title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    customer_signed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    special_terms: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    billing_address: Mapped[str | None] = mapped_column(String(500), nullable=True)

    account: Mapped["Account"] = relationship()  # noqa: F821 (crm_models.Account)
    agreement_type: Mapped["AgreementType"] = relationship()
    agreement_status: Mapped["AgreementStatus"] = relationship()
    supersedes_agreement: Mapped["Agreement | None"] = relationship(remote_side=[id])
    documents: Mapped[list["AgreementDocument"]] = relationship(back_populates="agreement")
    clauses: Mapped[list["AgreementClause"]] = relationship(back_populates="agreement")
    reviews: Mapped[list["AgreementReview"]] = relationship(back_populates="agreement")
    notes: Mapped[list["AgreementNote"]] = relationship(back_populates="agreement")


class AgreementDocument(Base, AuditMixin, SoftDeleteMixin):
    __tablename__ = "agreement_document"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agreement_id: Mapped[str] = mapped_column(ForeignKey("agreement.id"))
    version_number: Mapped[int] = mapped_column(default=1)
    sharepoint_item_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sharepoint_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(nullable=True)
    uploaded_by_source: Mapped[str | None] = mapped_column(String(30), nullable=True)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    agreement: Mapped["Agreement"] = relationship(back_populates="documents")


class AgreementClause(Base, AuditMixin, SoftDeleteMixin):
    __tablename__ = "agreement_clause"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agreement_id: Mapped[str] = mapped_column(ForeignKey("agreement.id"))
    section_ref: Mapped[str | None] = mapped_column(String(50), nullable=True)
    clause_text: Mapped[str] = mapped_column(String(4000))
    is_flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    flag_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    policy_ref: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resolution_status: Mapped[str | None] = mapped_column(String(30), nullable=True)

    agreement: Mapped["Agreement"] = relationship(back_populates="clauses")


class AgreementReview(Base, AuditMixin, SoftDeleteMixin):
    __tablename__ = "agreement_review"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agreement_id: Mapped[str] = mapped_column(ForeignKey("agreement.id"))
    reviewer_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reviewer_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True)
    summary: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    agreement: Mapped["Agreement"] = relationship(back_populates="reviews")


class AgreementNote(Base, AuditMixin, SoftDeleteMixin):
    """Running comments on an agreement — append-only (no update endpoint);
    AuditMixin's created_at/created_by already double as the note's
    timestamp/commenter metadata, so no separate columns are needed for it."""
    __tablename__ = "agreement_note"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agreement_id: Mapped[str] = mapped_column(ForeignKey("agreement.id"))
    note_text: Mapped[str] = mapped_column(String(2000))

    agreement: Mapped["Agreement"] = relationship(back_populates="notes")


# --- request/response (Pydantic) schemas ------------------------------------


class AgreementCreate(BaseModel):
    account_id: str
    agreement_type: str = Field(description="lookup code, e.g. NDA/MSA/SOW")
    title: str = Field(min_length=1, max_length=255)
    effective_date: date | None = None
    expiry_date: date | None = None
    sharepoint_folder_url: str | None = Field(default=None, max_length=1000)
    contract_term_months: int | None = None
    owner_expiration_notice_days: int | None = None
    customer_signed_contact_id: uuid.UUID | None = None
    customer_signed_title: str | None = Field(default=None, max_length=120)
    customer_signed_date: date | None = None
    special_terms: str | None = Field(default=None, max_length=2000)
    billing_address: str | None = Field(default=None, max_length=500)


class AgreementUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    status: str | None = Field(
        default=None, description="lookup code — not SIGNED/SUPERSEDED (use /sign, /supersede)")
    effective_date: date | None = None
    expiry_date: date | None = None
    sharepoint_folder_url: str | None = Field(default=None, max_length=1000)
    contract_term_months: int | None = None
    owner_expiration_notice_days: int | None = None
    customer_signed_contact_id: uuid.UUID | None = None
    customer_signed_title: str | None = Field(default=None, max_length=120)
    customer_signed_date: date | None = None
    special_terms: str | None = Field(default=None, max_length=2000)
    billing_address: str | None = Field(default=None, max_length=500)


class AgreementSupersedeRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    effective_date: date | None = None
    expiry_date: date | None = None


class AgreementOut(AuditOut):
    id: str
    account_id: str
    agreement_type: str
    status: str
    title: str
    initiated_by_employee_id: uuid.UUID | None = None
    effective_date: date | None = None
    expiry_date: date | None = None
    signed_at: datetime | None = None
    signed_by_employee_id: uuid.UUID | None = None
    supersedes_agreement_id: str | None = None
    sla_due_at: datetime | None = None
    sla_breached_at: datetime | None = None
    sharepoint_folder_url: str | None = None
    contract_term_months: int | None = None
    owner_expiration_notice_days: int | None = None
    customer_signed_contact_id: uuid.UUID | None = None
    customer_signed_title: str | None = None
    customer_signed_date: date | None = None
    special_terms: str | None = None
    billing_address: str | None = None


class AgreementClauseCreate(BaseModel):
    section_ref: str | None = Field(default=None, max_length=50)
    clause_text: str = Field(min_length=1, max_length=4000)
    policy_ref: str | None = Field(default=None, max_length=50)


class AgreementClauseUpdate(BaseModel):
    clause_text: str | None = Field(default=None, min_length=1, max_length=4000)
    is_flagged: bool | None = None
    flag_reason: str | None = Field(default=None, max_length=500)
    resolution_status: str | None = Field(default=None, max_length=30)


class AgreementClauseOut(AuditOut):
    id: uuid.UUID
    agreement_id: str
    section_ref: str | None = None
    clause_text: str
    is_flagged: bool
    flag_reason: str | None = None
    policy_ref: str | None = None
    resolution_status: str | None = None


class AgreementDocumentCreate(BaseModel):
    filename: str | None = Field(default=None, max_length=255)
    content_type: str | None = Field(default=None, max_length=120)
    size_bytes: int | None = None
    sharepoint_item_id: str | None = Field(default=None, max_length=255)
    sharepoint_url: str | None = Field(default=None, max_length=1000)


class AgreementDocumentOut(AuditOut):
    id: uuid.UUID
    agreement_id: str
    version_number: int
    sharepoint_item_id: str | None = None
    sharepoint_url: str | None = None
    filename: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None
    uploaded_by_source: str | None = None
    uploaded_at: datetime | None = None


class AgreementReviewCreate(BaseModel):
    reviewer_type: str = Field(default="HUMAN", max_length=30)
    summary: str | None = Field(default=None, max_length=2000)
    outcome: str = Field(max_length=30, description="e.g. APPROVED/NEEDS_AMENDMENT/REJECTED")


class AgreementReviewOut(AuditOut):
    id: uuid.UUID
    agreement_id: str
    reviewer_type: str | None = None
    reviewer_employee_id: uuid.UUID | None = None
    summary: str | None = None
    outcome: str | None = None
    reviewed_at: datetime | None = None


class AgreementNoteCreate(BaseModel):
    note_text: str = Field(min_length=1, max_length=2000)


class AgreementNoteOut(AuditOut):
    id: uuid.UUID
    agreement_id: str
    note_text: str
