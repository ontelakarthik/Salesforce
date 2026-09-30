"""Models for the Delivery module (§1/§9/§10 of the API spec) — SOW detail,
budget (versioned), rate card, team, milestones, timesheets, and (new)
Order + Revenue Recognition.

Full ORM schema implemented (the central "database logic" every developer
builds their service/route layer on top of) — business logic itself
(versioned budget revisions, effective-rate resolution, timesheet approval
rules) is NOT here; see services/delivery_service.py for what still needs to
be written, and repositories/delivery_repository.py for the ready-to-use
data-access classes.

Tables owned: sow_detail, sow_budget, sow_rate_card, sow_team_member,
sow_milestone, sow_timesheet, order (new), revenue_recognition_entry (new).
All key off agreement_id (a SOW is an agreement subtype owned by the
Contracts module — see contracts_models.py).

Order/RevenueRecognitionEntry are created automatically — not through a
public write endpoint — the moment a milestone is marked INVOICED (see
delivery_service.update_milestone()). They replace what used to be just a
free-text sow_milestone.invoice_ref with an actual, queryable revenue number,
denormalizing account_id/opportunity_id/campaign_id onto the recognition
entry (resolved once, at creation time, by walking
agreement→sow_detail.project_id→project.opportunity_id→opportunity.campaign_id)
so "revenue by campaign" is a plain query instead of a 4-table join every time.
"""
import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field
from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import AuditMixin, Base, SoftDeleteMixin
from src.models.common import AuditOut


class SowDetail(Base, AuditMixin):
    """1:1 extension of an agreement whose type is SOW — PK is the agreement's
    own id, not a separate surrogate key."""
    __tablename__ = "sow_detail"

    agreement_id: Mapped[str] = mapped_column(ForeignKey("agreement.id"), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), nullable=False)
    governing_msa_id: Mapped[str] = mapped_column(ForeignKey("agreement.id"), nullable=False)
    billing_model: Mapped[str | None] = mapped_column(String(30), nullable=True)
    total_value: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True, default="USD")
    headcount: Mapped[int | None] = mapped_column(nullable=True)
    invoicing_frequency: Mapped[str | None] = mapped_column(String(20), nullable=True)

    agreement: Mapped["Agreement"] = relationship(  # noqa: F821 (contracts_models.Agreement)
        foreign_keys=[agreement_id])
    governing_msa: Mapped["Agreement"] = relationship(  # noqa: F821
        foreign_keys=[governing_msa_id])
    project: Mapped["Project"] = relationship()  # noqa: F821 (project_models.Project)


class SowBudget(Base, AuditMixin, SoftDeleteMixin):
    __tablename__ = "sow_budget"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agreement_id: Mapped[str] = mapped_column(ForeignKey("agreement.id"))
    amount: Mapped[float] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    alert_threshold_percents: Mapped[str | None] = mapped_column(String(50), nullable=True)  # e.g. "70,80"
    effective_from: Mapped[date] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class SowRateCard(Base, AuditMixin, SoftDeleteMixin):
    __tablename__ = "sow_rate_card"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agreement_id: Mapped[str] = mapped_column(ForeignKey("agreement.id"))
    role_label: Mapped[str] = mapped_column(String(120))  # e.g. "Senior Engineer"
    rate_per_hour: Mapped[float] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    effective_from: Mapped[date] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    team_members: Mapped[list["SowTeamMember"]] = relationship(back_populates="rate_card")


class SowTeamMember(Base, AuditMixin, SoftDeleteMixin):
    __tablename__ = "sow_team_member"
    __table_args__ = (
        CheckConstraint(
            "(employee_id IS NOT NULL AND external_name IS NULL) OR "
            "(employee_id IS NULL AND external_name IS NOT NULL)",
            name="ck_sow_team_member_one_of_employee_or_external",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agreement_id: Mapped[str] = mapped_column(ForeignKey("agreement.id"))
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True)  # internal
    external_name: Mapped[str | None] = mapped_column(String(255), nullable=True)  # external
    rate_card_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sow_rate_card.id"), nullable=True)
    override_rate_per_hour: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    assigned_from: Mapped[date] = mapped_column(Date)
    assigned_until: Mapped[date | None] = mapped_column(Date, nullable=True)

    rate_card: Mapped["SowRateCard | None"] = relationship(back_populates="team_members")
    timesheets: Mapped[list["SowTimesheet"]] = relationship(back_populates="team_member")


class SowMilestone(Base, AuditMixin, SoftDeleteMixin):
    __tablename__ = "sow_milestone"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agreement_id: Mapped[str] = mapped_column(ForeignKey("agreement.id"))
    milestone_name: Mapped[str] = mapped_column(String(255))
    planned_date: Mapped[date] = mapped_column(Date)
    actual_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    invoiced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invoice_ref: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)


class SowTimesheet(Base, AuditMixin, SoftDeleteMixin):
    __tablename__ = "sow_timesheet"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sow_team_member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sow_team_member.id"))
    agreement_id: Mapped[str] = mapped_column(ForeignKey("agreement.id"))
    week_start_date: Mapped[date] = mapped_column(Date)
    hours: Mapped[float] = mapped_column(Numeric(5, 2))
    status: Mapped[str] = mapped_column(String(20), default="SUBMITTED")  # SUBMITTED|APPROVED|REJECTED
    submitted_by_employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employee.id"))
    approved_by_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    team_member: Mapped["SowTeamMember"] = relationship(back_populates="timesheets")


class Asset(Base, AuditMixin, SoftDeleteMixin):
    """What the account now owns as a result of delivery — the anchor for
    renewals, mirroring Salesforce's Asset object. One Asset per SOW,
    created the first time a milestone on it is invoiced (get-or-create in
    delivery_service._get_or_create_asset()); every later invoice against
    the same SOW recognizes revenue against this same Asset rather than
    minting a duplicate. renewed_by_opportunity_id is the other half of the
    loop: stamped once a renewal/cross-sell Opportunity is created against
    this Asset (see crm_service.create_opportunity()'s originating_asset_id
    handling) — this is the ERD's dashed "renewal / cross-sell" arrow, made
    real instead of just drawn."""
    __tablename__ = "asset"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[str] = mapped_column(ForeignKey("account.id"))
    agreement_id: Mapped[str] = mapped_column(ForeignKey("agreement.id"), unique=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaign.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    renewed_by_opportunity_id: Mapped[str | None] = mapped_column(
        ForeignKey("opportunity.id"), nullable=True)

    orders: Mapped[list["Order"]] = relationship(back_populates="asset")


class Order(Base, AuditMixin, SoftDeleteMixin):
    """Created automatically when a milestone is marked INVOICED — carries a
    direct account_id, mirroring Salesforce's Order.AccountId, rather than
    only being reachable by walking through the agreement."""
    __tablename__ = "order"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[str] = mapped_column(ForeignKey("account.id"))
    agreement_id: Mapped[str] = mapped_column(ForeignKey("agreement.id"))
    asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("asset.id"))
    milestone_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sow_milestone.id"))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVATED")
    amount: Mapped[float] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    order_date: Mapped[date] = mapped_column(Date)

    asset: Mapped["Asset"] = relationship(back_populates="orders")
    revenue_entry: Mapped["RevenueRecognitionEntry | None"] = relationship(back_populates="order")


class RevenueRecognitionEntry(Base, AuditMixin, SoftDeleteMixin):
    """The real, queryable number today's system doesn't have — replaces
    sow_milestone.invoice_ref (a text field) as the source of truth for
    "how much revenue did we recognize." opportunity_id/campaign_id are
    nullable because they're only resolvable when the SOW's project is
    itself linked to a Won opportunity that came through a Lead — the same
    honest gap called out in the architecture proposal for deals that predate
    Campaign/Lead."""
    __tablename__ = "revenue_recognition_entry"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("order.id"))
    asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("asset.id"))
    account_id: Mapped[str] = mapped_column(ForeignKey("account.id"))
    agreement_id: Mapped[str] = mapped_column(ForeignKey("agreement.id"))
    opportunity_id: Mapped[str | None] = mapped_column(ForeignKey("opportunity.id"), nullable=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaign.id"), nullable=True)
    recognized_amount: Mapped[float] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    recognized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    order: Mapped["Order"] = relationship(back_populates="revenue_entry")


# --- request/response (Pydantic) schemas ------------------------------------


class SowDetailUpsert(BaseModel):
    project_id: str
    governing_msa_id: str
    billing_model: str | None = Field(default=None, max_length=30)
    total_value: float | None = None
    currency: str = Field(default="USD", max_length=3)
    headcount: int | None = None
    invoicing_frequency: str | None = Field(default=None, max_length=20)


class SowDetailOut(BaseModel):
    agreement_id: str
    project_id: str
    governing_msa_id: str
    billing_model: str | None = None
    total_value: float | None = None
    currency: str | None = None
    headcount: int | None = None
    invoicing_frequency: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: str | None = None
    updated_by: str | None = None

    model_config = {"from_attributes": True}


class SowBudgetRevise(BaseModel):
    amount: float
    currency: str = Field(default="USD", max_length=3)
    alert_threshold_percents: str | None = Field(default=None, max_length=50, description="e.g. '70,80'")
    effective_from: date
    reason: str = Field(min_length=1, max_length=500)


class SowBudgetOut(AuditOut):
    id: uuid.UUID
    agreement_id: str
    amount: float
    currency: str
    alert_threshold_percents: str | None = None
    effective_from: date
    is_current: bool
    reason: str | None = None


class SowBudgetConsumptionOut(BaseModel):
    """Aggregate of APPROVED timesheet hours x each team member's effective
    rate (override_rate_per_hour, falling back to their rate card) against
    the current budget — computed on read, not stored."""
    agreement_id: str
    budget_amount: float | None = None
    consumed: float
    hours_logged: float
    consumed_percent: float | None = None


class SowRateCardCreate(BaseModel):
    role_label: str = Field(min_length=1, max_length=120)
    rate_per_hour: float
    currency: str = Field(default="USD", max_length=3)
    effective_from: date
    notes: str | None = Field(default=None, max_length=500)


class SowRateCardUpdate(BaseModel):
    rate_per_hour: float | None = None
    currency: str | None = Field(default=None, max_length=3)
    notes: str | None = Field(default=None, max_length=500)


class SowRateCardOut(AuditOut):
    id: uuid.UUID
    agreement_id: str
    role_label: str
    rate_per_hour: float
    currency: str
    effective_from: date
    notes: str | None = None


class SowTeamMemberCreate(BaseModel):
    employee_id: uuid.UUID | None = None
    external_name: str | None = Field(default=None, max_length=255)
    rate_card_id: uuid.UUID | None = None
    override_rate_per_hour: float | None = None
    assigned_from: date
    assigned_until: date | None = None


class SowTeamMemberUpdate(BaseModel):
    rate_card_id: uuid.UUID | None = None
    override_rate_per_hour: float | None = None
    assigned_until: date | None = None


class SowTeamMemberOut(AuditOut):
    id: uuid.UUID
    agreement_id: str
    employee_id: uuid.UUID | None = None
    external_name: str | None = None
    rate_card_id: uuid.UUID | None = None
    override_rate_per_hour: float | None = None
    assigned_from: date
    assigned_until: date | None = None


class SowMilestoneCreate(BaseModel):
    milestone_name: str = Field(min_length=1, max_length=255)
    planned_date: date
    amount: float | None = None
    notes: str | None = Field(default=None, max_length=500)


class SowMilestoneUpdate(BaseModel):
    actual_date: date | None = None
    status: str | None = Field(default=None, max_length=30)
    invoiced_at: datetime | None = None
    invoice_ref: str | None = Field(default=None, max_length=50)
    amount: float | None = None
    notes: str | None = Field(default=None, max_length=500)


class SowMilestoneOut(AuditOut):
    id: uuid.UUID
    agreement_id: str
    milestone_name: str
    planned_date: date
    actual_date: date | None = None
    amount: float | None = None
    status: str | None = None
    invoiced_at: datetime | None = None
    invoice_ref: str | None = None
    notes: str | None = None


class SowTimesheetCreate(BaseModel):
    sow_team_member_id: uuid.UUID
    agreement_id: str
    week_start_date: date
    hours: float
    notes: str | None = Field(default=None, max_length=500)


class SowTimesheetUpdate(BaseModel):
    hours: float | None = None
    notes: str | None = Field(default=None, max_length=500)


class SowTimesheetOut(AuditOut):
    id: uuid.UUID
    sow_team_member_id: uuid.UUID
    agreement_id: str
    week_start_date: date
    hours: float
    status: str
    submitted_by_employee_id: uuid.UUID
    approved_by_employee_id: uuid.UUID | None = None
    approved_at: datetime | None = None
    notes: str | None = None


class AssetOut(AuditOut):
    id: uuid.UUID
    account_id: str
    agreement_id: str
    campaign_id: uuid.UUID | None = None
    name: str
    status: str
    renewed_by_opportunity_id: str | None = None


class OrderOut(AuditOut):
    id: uuid.UUID
    account_id: str
    agreement_id: str
    asset_id: uuid.UUID
    milestone_id: uuid.UUID
    status: str
    amount: float
    currency: str
    order_date: date


class RevenueRecognitionEntryOut(AuditOut):
    id: uuid.UUID
    order_id: uuid.UUID
    asset_id: uuid.UUID
    account_id: str
    agreement_id: str
    opportunity_id: str | None = None
    campaign_id: uuid.UUID | None = None
    recognized_amount: float
    currency: str
    recognized_at: datetime
