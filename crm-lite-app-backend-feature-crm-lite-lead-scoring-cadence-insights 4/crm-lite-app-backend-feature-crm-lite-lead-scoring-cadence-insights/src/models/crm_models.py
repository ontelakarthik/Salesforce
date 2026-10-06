"""Models for the CRM module (§1/§6 of the API spec) — Accounts, Contacts,
Account assignments, Opportunities, Opportunity documents, Campaigns, Leads.

Full ORM schema implemented (the central "database logic" every developer
builds their service/route layer on top of) — business logic itself
(promote rules, scope rules, stage transitions, ...) is NOT here; see
services/crm_service.py for what still needs to be written, and
repositories/crm_repository.py for the ready-to-use data-access classes.

Tables owned: account_type (lookup), account, contact_type (lookup),
contact, account_assignment, opportunity_stage (lookup), opportunity,
opportunity_document, campaign, campaign_member, lead.

account_type/contact_type/opportunity_stage are reference data managed via
Admin's generic `/admin/lookups/{table}` endpoints (see admin_models.py) —
they live here, not in admin_models.py, because they belong conceptually to
the CRM domain and their tables are what CRM's own FKs point at.

Campaign/Lead are the front-of-funnel additions: a Lead converts into a
Account + Contact + Opportunity together (see crm_service.convert_lead()),
the same shape Salesforce's own Convert Lead produces — Account is this
system's "Account"-equivalent hub; it isn't renamed here since every other
module's FK, route, and RBAC capability already targets it by that name.
"""
import re
import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import AuditMixin, Base, SoftDeleteMixin
from src.utils.phone import normalize_phone
from src.models.common import AuditOut

# --- lookups -----------------------------------------------------------------





class AccountType(Base):
    __tablename__ = "account_type"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))


class ContactType(Base):
    __tablename__ = "contact_type"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))


class OpportunityStage(Base):
    __tablename__ = "opportunity_stage"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    is_terminal: Mapped[bool] = mapped_column(Boolean, default=False)


# --- core entities -------------------------------------------------------------


class Account(Base, AuditMixin, SoftDeleteMixin):
    __tablename__ = "account"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # e.g. ACC-00042
    legal_name: Mapped[str] = mapped_column(String(255))
    account_type_id: Mapped[int] = mapped_column(ForeignKey("account_type.id"))
    account_site: Mapped[str | None] = mapped_column(String(120), nullable=True)  # e.g. "Headquarters"
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)  # billing address
    shipping_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Structured Country -> State/Province (see src/utils/geo.py) — kept
    # alongside the free-text address/shipping_address above rather than
    # replacing them, and billing/shipping are independent pairs so editing
    # one never touches the other (see crm_service.create_account/
    # update_account's validation).
    billing_country: Mapped[str | None] = mapped_column(String(60), nullable=True)
    billing_state_province: Mapped[str | None] = mapped_column(String(60), nullable=True)
    shipping_country: Mapped[str | None] = mapped_column(String(60), nullable=True)
    shipping_state_province: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # Structured address parts. `address` is the Billing Street and
    # `shipping_address` the Shipping Street (the columns pre-date the
    # structured form, so existing free-text values simply read as the street).
    billing_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    billing_postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    shipping_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    shipping_postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    annual_revenue: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    num_employees: Mapped[int | None] = mapped_column(nullable=True)
    ownership: Mapped[str | None] = mapped_column(String(30), nullable=True)  # PUBLIC/PRIVATE/SUBSIDIARY/OTHER
    ticker_symbol: Mapped[str | None] = mapped_column(String(20), nullable=True)
    rating: Mapped[str | None] = mapped_column(String(10), nullable=True)  # HOT/WARM/COLD
    account_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sic_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    parent_account_id: Mapped[str | None] = mapped_column(ForeignKey("account.id"), nullable=True)
    owner_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True)
    # Sales Territory/Region — a business access-control concept, deliberately
    # separate from billing_country/billing_state_province above (see
    # admin_models.Territory's docstring). Defaulted once at create time from
    # the resolved owner's Employee.territory_id (see crm_service.
    # create_account()) and never auto-recomputed afterward, same treatment
    # as first_contact_at below — not itself a grant of access (see
    # services/record_access_service.py's module docstring for why Territory
    # never widens can_user_access_record()).
    territory_id: Mapped[int | None] = mapped_column(
        ForeignKey("territory.id"), nullable=True)
    first_contact_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    promoted_to_client_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    account_type: Mapped["AccountType"] = relationship()
    contacts: Mapped[list["Contact"]] = relationship(back_populates="account")
    assignments: Mapped[list["AccountAssignment"]] = relationship(back_populates="account")
    opportunities: Mapped[list["Opportunity"]] = relationship(back_populates="account")


class Contact(Base, AuditMixin, SoftDeleteMixin):
    __tablename__ = "contact"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[str] = mapped_column(ForeignKey("account.id"))
    contact_type_id: Mapped[int] = mapped_column(ForeignKey("contact_type.id"))
    salutation: Mapped[str | None] = mapped_column(String(20), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    department: Mapped[str | None] = mapped_column(String(120), nullable=True)
    birthdate: Mapped[date | None] = mapped_column(Date, nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mobile_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    home_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    other_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    assistant_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    assistant_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    lead_source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)  # mailing address
    other_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    reports_to_contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contact.id"), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    is_distribution_list: Mapped[bool] = mapped_column(Boolean, default=False)

    account: Mapped["Account"] = relationship(back_populates="contacts")
    contact_type: Mapped["ContactType"] = relationship()


class AccountAssignment(Base, AuditMixin, SoftDeleteMixin):
    __tablename__ = "account_assignment"
    __table_args__ = (
        CheckConstraint(
            "(employee_id IS NOT NULL AND team_id IS NULL) OR "
            "(employee_id IS NULL AND team_id IS NOT NULL)",
            name="ck_account_assignment_one_of_employee_or_team",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[str] = mapped_column(ForeignKey("account.id"))
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("team.id"), nullable=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("role.id"))
    assigned_from: Mapped[date] = mapped_column(Date)
    assigned_until: Mapped[date | None] = mapped_column(Date, nullable=True)

    account: Mapped["Account"] = relationship(back_populates="assignments")


class Opportunity(Base, AuditMixin, SoftDeleteMixin):
    __tablename__ = "opportunity"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # e.g. OPP-00031
    account_id: Mapped[str] = mapped_column(ForeignKey("account.id"))
    name: Mapped[str] = mapped_column(String(255))
    opportunity_stage_id: Mapped[int] = mapped_column(ForeignKey("opportunity_stage.id"))
    estimated_value: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True, default="USD")
    expected_close_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    owner_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True)
    lost_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    probability_percent: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    opportunity_type: Mapped[str | None] = mapped_column(String(30), nullable=True)  # NEW_BUSINESS/EXISTING_BUSINESS/RENEWAL/UPGRADE
    next_step: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    # Attribution — set once, either by convert_lead() (both populated together)
    # or left null for an opportunity created directly (today's only path).
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead.id"), nullable=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaign.id"), nullable=True)
    # Set when this Opportunity is a renewal/cross-sell created against an
    # existing Asset (see crm_service.create_opportunity()) — the other half
    # of Asset.renewed_by_opportunity_id, closing the ERD's renewal loop.
    originating_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("asset.id"), nullable=True)

    account: Mapped["Account"] = relationship(back_populates="opportunities")
    stage: Mapped["OpportunityStage"] = relationship()
    documents: Mapped[list["OpportunityDocument"]] = relationship(back_populates="opportunity")


class OpportunityDocument(Base, AuditMixin, SoftDeleteMixin):
    __tablename__ = "opportunity_document"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunity.id"))
    version_number: Mapped[int] = mapped_column(default=1)
    doc_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    sharepoint_item_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sharepoint_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    opportunity: Mapped["Opportunity"] = relationship(back_populates="documents")


class Campaign(Base, AuditMixin, SoftDeleteMixin):
    """A marketing initiative — the top of the funnel, upstream of anything
    else in this module. Deliberately simple (no lookup table for
    campaign_type): a handful of free-text/low-cardinality values, not
    admin-managed reference data."""
    __tablename__ = "campaign"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    campaign_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # e.g. WEBINAR/EMAIL/EVENT
    status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # PLANNED/IN_PROGRESS/COMPLETED/ABORTED
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    budgeted_cost: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    actual_cost: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    expected_revenue: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    expected_response_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    num_sent: Mapped[int | None] = mapped_column(nullable=True)
    parent_campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaign.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Added for OWD/record-access (see services.record_access_service) — Campaign
    # previously had no owner and no scope check at all; every profile with
    # platform.read saw every campaign. Nullable so pre-existing rows (backfilled
    # to NULL by the introducing migration) simply have no owner-based access
    # until one is explicitly set, same treatment as Account/Lead/Opportunity's
    # owner_employee_id when those were first introduced.
    owner_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True)

    members: Mapped[list["CampaignMember"]] = relationship(back_populates="campaign")
    leads: Mapped[list["Lead"]] = relationship(back_populates="campaign")


class CampaignMember(Base, AuditMixin, SoftDeleteMixin):
    """Links a Lead to a Campaign with a response status — mirrors
    Salesforce's CampaignMember. Scoped to Lead only (not Contact) for now:
    membership after conversion is answered by Opportunity.campaign_id /
    Opportunity.lead_id, not by a second CampaignMember row."""
    __tablename__ = "campaign_member"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("campaign.id"))
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("lead.id"))
    status: Mapped[str | None] = mapped_column(String(30), nullable=True)  # e.g. SENT/RESPONDED/REGISTERED

    campaign: Mapped["Campaign"] = relationship(back_populates="members")
    lead: Mapped["Lead"] = relationship(back_populates="campaign_memberships")


class Lead(Base, AuditMixin, SoftDeleteMixin):
    """Front-of-funnel record, ahead of Account/Opportunity even existing.
    convert_lead() (crm_service.py) is the one-time, atomic action that turns
    a QUALIFIED lead into an Account + Contact + Opportunity — after which
    this row is marked CONVERTED and keeps the three ids it produced, exactly
    like Salesforce's ConvertedAccountId/ConvertedContactId/
    ConvertedOpportunityId."""
    __tablename__ = "lead"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaign.id"), nullable=True)
    # An existing Account this Lead is associated with, set by the rep
    # picking one on the Lead form (see crm_service.create_lead()/
    # update_lead()) — distinct from converted_account_id below, which is
    # only ever stamped by convert_lead() once, atomically with the other
    # two converted_* ids. This one is freely re-settable pre-conversion and
    # only drives the UI's Account -> Lead field auto-population; it plays
    # no part in convert_lead() itself.
    account_id: Mapped[str | None] = mapped_column(ForeignKey("account.id"), nullable=True)
    company_name: Mapped[str] = mapped_column(String(255))
    salutation: Mapped[str | None] = mapped_column(String(20), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_name: Mapped[str] = mapped_column(String(120))
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Required (Lead email is the core communication channel — cadence/
    # follow-up depends on it); enforced NOT NULL here and format-validated
    # in LeadCreate/LeadUpdate above (see migration that backfills any
    # pre-existing NULL rows before adding this constraint).
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mobile_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # No embedded LinkedIn messaging/posting — LinkedIn has no public API for
    # that (only partner-only programs like Sales Navigator API, a business
    # relationship, not just a credential). This is a deep link out to the
    # lead's own profile; the actual message/connect happens on linkedin.com
    # itself, then the rep logs it via the existing LINKEDIN communication
    # channel (see activity_models.Communication).
    linkedin_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    rating: Mapped[str | None] = mapped_column(String(10), nullable=True)  # HOT/WARM/COLD
    annual_revenue: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    num_employees: Mapped[int | None] = mapped_column(nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Structured Country -> State/Province (see src/utils/geo.py), alongside
    # the free-text address above. Region is deliberately NOT a column here
    # — it's derived fresh from these two on every read (see
    # crm_service._lead_out()) so it can never go stale.
    country: Mapped[str | None] = mapped_column(String(60), nullable=True)
    state_province: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # `address` above is the Street; city/postal_code complete the structured address.
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    do_not_call: Mapped[bool] = mapped_column(Boolean, default=False)
    email_opt_out: Mapped[bool] = mapped_column(Boolean, default=False)
    # WhatsApp (Twilio WhatsApp Business API, see services/whatsapp_service.py)
    # — E.164 format only (e.g. "+919876543210"); Twilio's "whatsapp:" prefix
    # must never be stored here, it's added/stripped only in the integrations/
    # twilio_whatsapp.py boundary layer. whatsapp_opt_in is a hard backend
    # precondition for sending (checked in whatsapp_service.py, not just the
    # UI) — opt_in_source/opt_in_at record how/when consent was captured
    # (e.g. "MANUAL" via a rep, "INBOUND_STOP" when set back to False by an
    # opt-out keyword). whatsapp_window_expires_at is Twilio's 24-hour
    # customer-service-window deadline, refreshed to now+24h on every inbound
    # message; a NULL/past value means only an approved template may be sent.
    whatsapp_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    whatsapp_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    whatsapp_opt_in_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    whatsapp_opt_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    whatsapp_window_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="NEW")  # see models.enums.LeadStatus
    # Internal, backend-only "has this lead ever been successfully contacted"
    # flag — deliberately absent from LeadCreate/LeadUpdate/LeadOut and
    # _FLS_FIELDS, so it can't be set or seen through the API/UI. Flipped
    # exactly once, by activity_service.mark_lead_as_contacted_if_first_contact()
    # after the first successful Email/SMS/Call; once True, those activities
    # never auto-change status again (the rep's manual status is left alone).
    contacted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    lead_score: Mapped[int] = mapped_column(default=0)  # system-computed, see crm_service._compute_lead_score
    # Web-enriched scoring (BRD SC-2) — the live-web-search component of
    # lead_score, kept separate from the rule-based component so re-running
    # enrichment or editing the lead never silently drops the other's
    # contribution (see crm_service._total_lead_score()).
    web_enrichment_points: Mapped[int | None] = mapped_column(nullable=True)
    web_enrichment_summary: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    web_enrichment_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Pulse (verified external Signal rows, see the Signal model below) — the
    # decayed, capped sum of this lead's own signals' current contribution,
    # kept separate from web_enrichment_points for the exact same reason:
    # sourcing a new signal batch, or a signal simply aging out, must never
    # silently drop the other component's points (see
    # crm_service._total_lead_score() / _recompute_signal_points()).
    signal_points: Mapped[int | None] = mapped_column(nullable=True)
    owner_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True)
    # Sales Territory/Region — see Account.territory_id's identical comment
    # just above in this same file; defaulted the same way in
    # crm_service.create_lead().
    territory_id: Mapped[int | None] = mapped_column(
        ForeignKey("territory.id"), nullable=True)
    converted_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("account.id"), nullable=True)
    converted_contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contact.id"), nullable=True)
    converted_opportunity_id: Mapped[str | None] = mapped_column(
        ForeignKey("opportunity.id"), nullable=True)
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    campaign: Mapped["Campaign | None"] = relationship(back_populates="leads")
    campaign_memberships: Mapped[list["CampaignMember"]] = relationship(back_populates="lead")


class LeadScoringRule(Base, AuditMixin, SoftDeleteMixin):
    """Admin-managed config that drives Lead.lead_score (see
    crm_service._compute_lead_score()) — global, not owned by any one
    employee, same treatment as Campaign. field_name is validated in the
    service layer against a fixed allow-list of scorable Lead columns."""
    __tablename__ = "lead_scoring_rule"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    field_name: Mapped[str] = mapped_column(String(60))
    operator: Mapped[str] = mapped_column(String(20))  # see models.enums.LeadScoringOperator
    comparison_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    points: Mapped[int] = mapped_column()
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Signal(Base, AuditMixin):
    """Pulse — one verified external signal (a hiring surge, an RFP, a
    funding round, ...) about a company, sourced by
    crm_service.ingest_signals() (mock adapters today — see
    crm_service._MOCK_SIGNAL_SOURCES; swapping in a real feed later is one
    more source function, never a change to this table or the scoring below).

    Immutable evidence, not admin-editable config — no SoftDeleteMixin (a
    signal is either real or it isn't; nothing here is ever "undeleted") and
    CrudRepository, not SoftDeleteCrudRepository, backs it (see
    repositories/crm_repository.SignalRepository).

    lead_id is nullable: ingest_signals() sources signals by company name
    first and only resolves/creates the owning Lead afterward (see
    LeadRepository.find_by_company_name()), so a signal can transiently
    exist before its lead does within one ingest run — never left null once
    that run completes.

    `strength` (0..1, the source's own confidence/magnitude) is the stored,
    time-invariant fact; the *decayed* 0..40 point contribution a signal
    makes to its lead's score right now is computed on read, never stored,
    so a signal quietly ages out of the score without any write happening to
    it (see crm_service._signal_decay_points())."""
    __tablename__ = "signal"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("lead.id"), nullable=True)
    company_name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(30))  # see models.enums.SignalType
    source: Mapped[str] = mapped_column(String(120))
    summary: Mapped[str] = mapped_column(String(1000))
    strength: Mapped[float] = mapped_column(Numeric(3, 2))  # 0.00..1.00
    practice_hint: Mapped[str | None] = mapped_column(String(60), nullable=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # ingest_signals() dedupes a mock-catalog entry against this triple
        # (not captured_at — a mock run's "now" shifts a few seconds between
        # any two calls, and the same catalog entry must still be recognized
        # as already-sourced) so re-running it doesn't create the same
        # signal twice. A real feed would key on its own event id instead
        # and could legitimately see the same (company, type, source) recur
        # over time — this constraint is mock-catalog shaped, not a
        # permanent modeling choice.
        UniqueConstraint("company_name", "type", "source", name="uq_signal_identity"),
    )


class FieldPermission(Base, AuditMixin, SoftDeleteMixin):
    """Admin-managed Field-Level Security — per (role, object, field) row
    saying whether that role can see/edit that field, layered on top of
    (never replacing) the existing object-level capability grants (see
    utils.permissions.CAPABILITY_REGISTRY / admin_models.ProfileCapability)
    and row-level ownership scoping. No row for a (role, object, field) means
    fully permissive — see crm_service.get_effective_field_permissions()
    for how multiple held roles combine (union/most-permissive-wins) and
    which fields are even eligible (crm_service._FLS_FIELDS)."""
    __tablename__ = "field_permission"
    # Partial (not a plain UniqueConstraint) so a soft-deleted row never
    # blocks a future insert reusing the same (role, object, field) key —
    # crm_service.save_field_permissions() hard-deletes these rows itself
    # on every full-matrix replace, but a partial index means this table
    # stays correct even if something ever calls the inherited soft
    # SoftDeleteCrudRepository.delete() on it instead.
    __table_args__ = (
        Index(
            "ix_field_permission_role_object_field", "role_id", "object_name", "field_name",
            unique=True, postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_id: Mapped[int] = mapped_column(ForeignKey("role.id"))
    object_name: Mapped[str] = mapped_column(String(20))  # LEAD | ACCOUNT | OPPORTUNITY
    field_name: Mapped[str] = mapped_column(String(60))
    visible: Mapped[bool] = mapped_column(Boolean, default=True)
    editable: Mapped[bool] = mapped_column(Boolean, default=True)


class OrgWideDefault(Base, AuditMixin):
    """Admin-managed Organization-Wide Default — one row per OWD-eligible
    object (LEAD | ACCOUNT | CONTACT | OPPORTUNITY | CAMPAIGN, same
    vocabulary as FieldPermission.object_name) giving the baseline
    row-visibility everyone gets before row ownership, sharing (see
    RecordShare below), or the records.see_all capability widen it further
    — see services.record_access_service.can_user_access_record(). PRIVATE
    means owner (+ a Role-Hierarchy manager of the owner, + an explicit
    RecordShare) only; PUBLIC_READ_ONLY opens reads to everyone but leaves
    writes owner/manager/share gated; PUBLIC_READ_WRITE opens both. This row
    itself stays a flat, non-hierarchical baseline — see
    record_access_service's module docstring for how Role Hierarchy and
    Territory each factor (or deliberately don't) into the layer built on
    top of it.

    Exactly 5 permanent rows (LEAD/ACCOUNT/OPPORTUNITY seeded by the
    original migration; CONTACT/CAMPAIGN backfilled by a later additive
    one), only ever updated in place via PUT /admin/org-wide-defaults —
    unlike FieldPermission this is never created/deleted through the API,
    so no SoftDeleteMixin."""
    __tablename__ = "org_wide_default"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    object_name: Mapped[str] = mapped_column(String(20), unique=True)  # LEAD|ACCOUNT|CONTACT|OPPORTUNITY|CAMPAIGN
    access_level: Mapped[str] = mapped_column(String(20))  # see models.enums.OrgWideDefaultAccessLevel


class RecordShare(Base, AuditMixin, SoftDeleteMixin):
    """Salesforce-style user-based record sharing — the one mechanism (besides
    ownership and OWD) that can grant a non-owner access to an otherwise
    PRIVATE (or read-only-under-OWD) record. See
    services.record_access_service.can_user_access_record(): a share can only
    ADD access on top of OWD/ownership, never remove it, and never grants
    DELETE (access_level is READ|EDIT only — see models.enums.
    RecordAccessLevel, which DELETE is deliberately excluded from here).

    record_id is a plain string, not a typed FK: the 5 sharable objects have
    different primary-key shapes (Account's is a "ACC-00042"-style business
    id; Lead/Contact/Opportunity/Campaign are UUIDs) — same polymorphic-
    reference trade-off FieldPermission.object_name/field_name already
    accepts, validated in the service layer (crm_service.create_record_share())
    rather than at the DB level. Employee-only for this first cut — no
    team_id column, deliberately: this feature explicitly excludes
    Role-Hierarchy/team/group-based sharing, only a specific user."""
    __tablename__ = "record_share"
    __table_args__ = (
        Index(
            "ix_record_share_object_record_employee", "object_name", "record_id",
            "shared_with_employee_id", unique=True, postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_record_share_object_record", "object_name", "record_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    object_name: Mapped[str] = mapped_column(String(20))  # LEAD|ACCOUNT|CONTACT|OPPORTUNITY|CAMPAIGN
    record_id: Mapped[str] = mapped_column(String(40))
    shared_with_employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employee.id"))
    access_level: Mapped[str] = mapped_column(String(10))  # READ | EDIT — see models.enums.RecordAccessLevel
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Product(Base, AuditMixin, SoftDeleteMixin):
    """Our own catalog of what we sell — admin-managed, global (no owner
    scoping, same treatment as Campaign/LeadScoringRule). Consumed by
    crm_service.generate_email_draft()/generate_call_prep(), which research a
    lead's company via live web search and ask the model to pick the
    best-matching active product(s) for a personalized pitch, rather than
    hand-waving at "our product" generically."""
    __tablename__ = "product"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(String(2000))
    target_industry: Mapped[str | None] = mapped_column(
        String(120), nullable=True)  # e.g. "Healthcare" — null means general-purpose
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


# --- Sales Cadence -----------------------------------------------------------


class CadenceTemplate(Base, AuditMixin, SoftDeleteMixin):
    """A reusable, admin-authored sequence of outreach steps a Lead can be
    enrolled into (see crm_service.enroll_lead_in_cadence()). No owner
    scoping — every role with platform.read sees every template, same as
    Campaign."""
    __tablename__ = "cadence_template"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    steps: Mapped[list["CadenceStep"]] = relationship(
        back_populates="cadence_template", order_by="CadenceStep.step_order")


class CadenceStep(Base, AuditMixin, SoftDeleteMixin):
    __tablename__ = "cadence_step"
    __table_args__ = (
        UniqueConstraint("cadence_template_id", "step_order", name="uq_cadence_step_template_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cadence_template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cadence_template.id", ondelete="CASCADE"))
    step_order: Mapped[int] = mapped_column()
    step_type: Mapped[str] = mapped_column(String(20))  # see models.enums.CadenceStepType
    subject: Mapped[str] = mapped_column(String(255))
    instructions: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    wait_days: Mapped[int] = mapped_column()
    # False (the default) preserves the original calendar-day behavior —
    # wait_days counts every day. True counts only Mon-Fri (see
    # crm_service._compute_due_date(), the one shared calculation used by
    # both enroll_lead_in_cadence() and complete_cadence_task()/
    # advance_due_cadence_steps()).
    skip_weekends: Mapped[bool] = mapped_column(Boolean, default=False)

    cadence_template: Mapped["CadenceTemplate"] = relationship(back_populates="steps")


class LeadCadenceEnrollment(Base, AuditMixin, SoftDeleteMixin):
    """A Lead's run through a CadenceTemplate. Only one ACTIVE enrollment per
    lead at a time — enforced in crm_service.enroll_lead_in_cadence(), not
    here (a value-in-column business rule, same treatment as LeadStatus's
    transition rules)."""
    __tablename__ = "lead_cadence_enrollment"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("lead.id"))
    cadence_template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cadence_template.id"))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")  # see models.enums.LeadCadenceEnrollmentStatus
    current_step_order: Mapped[int] = mapped_column()
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    enrolled_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True)


class CadenceTask(Base, AuditMixin, SoftDeleteMixin):
    """One task per CadenceStep, created on demand — never client-created
    directly (see crm_service.enroll_lead_in_cadence()/complete_cadence_task()),
    same treatment as Lead.converted_* fields."""
    __tablename__ = "cadence_task"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enrollment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead_cadence_enrollment.id"))
    cadence_step_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cadence_step.id"))
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")  # see models.enums.CadenceTaskStatus
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    # True only when the SCHEDULER (crm_service.advance_due_cadence_steps())
    # resolved this task itself (a due BREAK, or a FOLLOW_UP auto-skipped
    # because the lead already replied) rather than a rep completing/
    # skipping it by hand via POST /cadence-tasks/{id}/complete.
    auto_resolved: Mapped[bool] = mapped_column(Boolean, default=False)


# --- request/response (Pydantic) schemas ------------------------------------
# account_type is intentionally NOT part of Create/Update — new accounts
# always start as PROSPECT and only move to CLIENT through the dedicated
# /promote endpoint (see services/crm_service.py).


class AccountCreate(BaseModel):
    legal_name: str = Field(min_length=2, max_length=255)
    account_site: str | None = Field(default=None, max_length=120)
    industry: str | None = Field(default=None, max_length=120)
    website: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, max_length=500)
    shipping_address: str | None = Field(default=None, max_length=500)
    billing_country: str | None = Field(default=None, description="USA | Canada")
    billing_state_province: str | None = Field(default=None, max_length=60)
    shipping_country: str | None = Field(default=None, description="USA | Canada")
    shipping_state_province: str | None = Field(default=None, max_length=60)
    billing_city: str | None = Field(default=None, max_length=100)
    billing_postal_code: str | None = Field(default=None, max_length=20)
    shipping_city: str | None = Field(default=None, max_length=100)
    shipping_postal_code: str | None = Field(default=None, max_length=20)
    annual_revenue: float | None = None
    num_employees: int | None = None
    ownership: str | None = Field(default=None, description="PUBLIC | PRIVATE | SUBSIDIARY | OTHER")
    ticker_symbol: str | None = Field(default=None, max_length=20)
    rating: str | None = Field(default=None, description="HOT | WARM | COLD")
    account_number: str | None = Field(default=None, max_length=40)
    sic_code: str | None = Field(default=None, max_length=20)
    description: str | None = Field(default=None, max_length=2000)
    parent_account_id: str | None = None
    owner_employee_id: uuid.UUID | None = None


class AccountUpdate(BaseModel):
    legal_name: str | None = Field(default=None, min_length=2, max_length=255)
    account_site: str | None = Field(default=None, max_length=120)
    industry: str | None = Field(default=None, max_length=120)
    website: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, max_length=500)
    shipping_address: str | None = Field(default=None, max_length=500)
    billing_country: str | None = Field(default=None, description="USA | Canada")
    billing_state_province: str | None = Field(default=None, max_length=60)
    shipping_country: str | None = Field(default=None, description="USA | Canada")
    shipping_state_province: str | None = Field(default=None, max_length=60)
    billing_city: str | None = Field(default=None, max_length=100)
    billing_postal_code: str | None = Field(default=None, max_length=20)
    shipping_city: str | None = Field(default=None, max_length=100)
    shipping_postal_code: str | None = Field(default=None, max_length=20)
    annual_revenue: float | None = None
    num_employees: int | None = None
    ownership: str | None = Field(default=None, description="PUBLIC | PRIVATE | SUBSIDIARY | OTHER")
    ticker_symbol: str | None = Field(default=None, max_length=20)
    rating: str | None = Field(default=None, description="HOT | WARM | COLD")
    account_number: str | None = Field(default=None, max_length=40)
    sic_code: str | None = Field(default=None, max_length=20)
    description: str | None = Field(default=None, max_length=2000)
    parent_account_id: str | None = None
    owner_employee_id: uuid.UUID | None = None


class AccountOut(AuditOut):
    id: str
    # legal_name is NOT NULL at create time — Optional here only so FLS
    # redaction (crm_service._redact()) can null it for a restricted role.
    legal_name: str | None = None
    account_type: str  # lookup code, e.g. PROSPECT/CLIENT
    account_site: str | None = None
    industry: str | None = None
    website: str | None = None
    phone: str | None = None
    address: str | None = None
    shipping_address: str | None = None
    billing_country: str | None = None
    billing_state_province: str | None = None
    # Derived, same as LeadOut.region — never stored, always recomputed from
    # billing_country + billing_state_province (see src/utils/geo.py) so it
    # can never drift out of sync with them.
    region: str | None = None
    shipping_country: str | None = None
    shipping_state_province: str | None = None
    billing_city: str | None = None
    billing_postal_code: str | None = None
    shipping_city: str | None = None
    shipping_postal_code: str | None = None
    annual_revenue: float | None = None
    num_employees: int | None = None
    ownership: str | None = None
    ticker_symbol: str | None = None
    rating: str | None = None
    account_number: str | None = None
    sic_code: str | None = None
    description: str | None = None
    parent_account_id: str | None = None
    owner_employee_id: uuid.UUID | None = None
    # Sales Territory/Region (see admin_models.Territory) — a business
    # access-control concept, distinct from billing_country/region above.
    # Read-only: never accepted on AccountCreate/AccountUpdate, always
    # server-defaulted from the owner's Employee.territory_id (see
    # crm_service.create_account()).
    territory: str | None = None
    first_contact_at: datetime | None = None
    promoted_to_client_at: datetime | None = None
    can_edit: bool = True
    can_delete: bool = True


class ContactCreate(BaseModel):
    contact_type: str = Field(description="lookup code, e.g. BUSINESS/LEGAL/PROCUREMENT")
    salutation: str | None = Field(default=None, max_length=20)
    full_name: str = Field(min_length=1, max_length=255)
    title: str | None = Field(default=None, max_length=120)
    department: str | None = Field(default=None, max_length=120)
    birthdate: date | None = None
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    mobile_phone: str | None = Field(default=None, max_length=50)
    home_phone: str | None = Field(default=None, max_length=50)
    other_phone: str | None = Field(default=None, max_length=50)
    assistant_name: str | None = Field(default=None, max_length=255)
    assistant_phone: str | None = Field(default=None, max_length=50)
    lead_source: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=500)
    other_address: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=2000)
    reports_to_contact_id: uuid.UUID | None = None
    is_primary: bool = False
    is_distribution_list: bool = False


class ContactUpdate(BaseModel):
    contact_type: str | None = None
    salutation: str | None = Field(default=None, max_length=20)
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    title: str | None = Field(default=None, max_length=120)
    department: str | None = Field(default=None, max_length=120)
    birthdate: date | None = None
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    mobile_phone: str | None = Field(default=None, max_length=50)
    home_phone: str | None = Field(default=None, max_length=50)
    other_phone: str | None = Field(default=None, max_length=50)
    assistant_name: str | None = Field(default=None, max_length=255)
    assistant_phone: str | None = Field(default=None, max_length=50)
    lead_source: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=500)
    other_address: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=2000)
    reports_to_contact_id: uuid.UUID | None = None
    is_primary: bool | None = None
    is_distribution_list: bool | None = None


class ContactOut(AuditOut):
    id: uuid.UUID
    account_id: str
    contact_type: str
    salutation: str | None = None
    full_name: str
    title: str | None = None
    department: str | None = None
    birthdate: date | None = None
    email: str | None = None
    phone: str | None = None
    mobile_phone: str | None = None
    home_phone: str | None = None
    other_phone: str | None = None
    assistant_name: str | None = None
    assistant_phone: str | None = None
    lead_source: str | None = None
    address: str | None = None
    other_address: str | None = None
    description: str | None = None
    reports_to_contact_id: uuid.UUID | None = None
    is_primary: bool
    is_distribution_list: bool
    can_edit: bool = True
    can_delete: bool = True


class AccountAssignmentCreate(BaseModel):
    employee_id: uuid.UUID | None = None
    team_id: int | None = None
    role: str = Field(description="lookup code, e.g. SALES/ACCOUNT_EXEC/LEADERSHIP/ADMIN")
    assigned_from: date
    assigned_until: date | None = None


class AccountAssignmentUpdate(BaseModel):
    role: str | None = None
    assigned_until: date | None = None


class AccountAssignmentOut(AuditOut):
    id: uuid.UUID
    account_id: str
    employee_id: uuid.UUID | None = None
    team_id: int | None = None
    role: str
    assigned_from: date
    assigned_until: date | None = None


class OpportunityCreate(BaseModel):
    account_id: str
    name: str = Field(min_length=1, max_length=255)
    estimated_value: float | None = None
    currency: str = Field(default="USD", max_length=3)
    expected_close_date: date | None = None
    owner_employee_id: uuid.UUID | None = None
    probability_percent: float | None = None
    opportunity_type: str | None = Field(
        default=None, description="NEW_BUSINESS | EXISTING_BUSINESS | RENEWAL | UPGRADE")
    next_step: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    originating_asset_id: uuid.UUID | None = Field(
        default=None,
        description="Set to renew/cross-sell against an existing Asset — auto-inherits its "
                    "campaign_id unless campaign_id is also given, and stamps the Asset's "
                    "renewed_by_opportunity_id back to this Opportunity once created.",
    )


class OpportunityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    stage: str | None = Field(default=None, description="lookup code, e.g. QUALIFIED/WON/LOST")
    estimated_value: float | None = None
    currency: str | None = Field(default=None, max_length=3)
    expected_close_date: date | None = None
    owner_employee_id: uuid.UUID | None = None
    lost_reason: str | None = Field(default=None, max_length=500)
    probability_percent: float | None = None
    opportunity_type: str | None = Field(
        default=None, description="NEW_BUSINESS | EXISTING_BUSINESS | RENEWAL | UPGRADE")
    next_step: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class OpportunityOut(AuditOut):
    id: str
    account_id: str
    # name is NOT NULL at create time — Optional here only so FLS redaction
    # (crm_service._redact()) can null it for a restricted role.
    name: str | None = None
    stage: str
    estimated_value: float | None = None
    currency: str | None = None
    expected_close_date: date | None = None
    owner_employee_id: uuid.UUID | None = None
    lost_reason: str | None = None
    probability_percent: float | None = None
    opportunity_type: str | None = None
    next_step: str | None = None
    description: str | None = None
    lead_id: uuid.UUID | None = None
    campaign_id: uuid.UUID | None = None
    originating_asset_id: uuid.UUID | None = None
    can_edit: bool = True
    can_delete: bool = True


class OpportunityDocumentCreate(BaseModel):
    doc_type: str | None = Field(default=None, max_length=50)
    filename: str | None = Field(default=None, max_length=255)
    sharepoint_item_id: str | None = Field(default=None, max_length=255)
    sharepoint_url: str | None = Field(default=None, max_length=1000)


class OpportunityDocumentUpdate(BaseModel):
    status: str | None = Field(default=None, max_length=30)
    filename: str | None = Field(default=None, max_length=255)
    sharepoint_item_id: str | None = Field(default=None, max_length=255)
    sharepoint_url: str | None = Field(default=None, max_length=1000)


class OpportunityDocumentOut(AuditOut):
    id: uuid.UUID
    opportunity_id: str
    version_number: int
    doc_type: str | None = None
    status: str | None = None
    sharepoint_item_id: str | None = None
    sharepoint_url: str | None = None
    filename: str | None = None
    uploaded_at: datetime | None = None


# --- Campaigns -----------------------------------------------------------------


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    campaign_type: str | None = Field(default=None, max_length=50)
    status: str | None = Field(default=None, description="PLANNED | IN_PROGRESS | COMPLETED | ABORTED")
    start_date: date | None = None
    end_date: date | None = None
    description: str | None = Field(default=None, max_length=2000)
    budgeted_cost: float | None = None
    actual_cost: float | None = None
    expected_revenue: float | None = None
    expected_response_pct: float | None = None
    num_sent: int | None = None
    parent_campaign_id: uuid.UUID | None = None
    owner_employee_id: uuid.UUID | None = None


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    campaign_type: str | None = Field(default=None, max_length=50)
    status: str | None = Field(default=None, description="PLANNED | IN_PROGRESS | COMPLETED | ABORTED")
    start_date: date | None = None
    end_date: date | None = None
    description: str | None = Field(default=None, max_length=2000)
    budgeted_cost: float | None = None
    actual_cost: float | None = None
    expected_revenue: float | None = None
    expected_response_pct: float | None = None
    num_sent: int | None = None
    parent_campaign_id: uuid.UUID | None = None
    is_active: bool | None = None
    owner_employee_id: uuid.UUID | None = None


class CampaignOut(AuditOut):
    id: uuid.UUID
    name: str
    campaign_type: str | None = None
    status: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    description: str | None = None
    budgeted_cost: float | None = None
    actual_cost: float | None = None
    expected_revenue: float | None = None
    expected_response_pct: float | None = None
    num_sent: int | None = None
    parent_campaign_id: uuid.UUID | None = None
    is_active: bool
    owner_employee_id: uuid.UUID | None = None
    can_edit: bool = True
    can_delete: bool = True


class CampaignSendRequest(BaseModel):
    """Payload for POST /campaigns/{id}/send — blasts this subject/body to
    every lead with campaign_id == this campaign that the caller can see
    (scoped the same way list_leads(campaign_id=...) is), skipping leads
    with no contact_email or email_opt_out=True. One send failure doesn't
    abort the rest — see CampaignSendResult for the per-outcome counts."""
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1)


class CampaignSendResult(BaseModel):
    campaign_id: uuid.UUID
    total_targeted: int
    sent: int
    skipped_no_email: int
    skipped_opted_out: int
    failed: int


class EmailIntakeResult(BaseModel):
    """Response for POST /email-intake/poll — a sender with no existing Lead
    (matched by contact_email) becomes a new one; a sender who already has a
    Lead gets an INBOUND Communication logged against it instead of a
    duplicate. errors counts messages that failed to process (each one is
    skipped, not fatal to the rest of the poll)."""
    messages_processed: int
    leads_created: int
    matched_existing_lead: int
    errors: int


class SmsIntakeResult(BaseModel):
    """Response for POST /sms-intake/webhook — one Twilio webhook call is
    exactly one inbound SMS (unlike email-intake's poll-many-at-once shape).
    Unlike inbound email, an unmatched sender does NOT become a new Lead:
    Lead.contact_email is required (NOT NULL) and an SMS reply carries no
    email address to satisfy it, so a text from a number not already on
    file (Lead.contact_phone/mobile_phone) is simply not logged against any
    record — matched_lead=False is the signal an AE/ADMIN needs to go
    create that Lead by hand first."""
    matched_lead: bool
    lead_id: uuid.UUID | None = None
    communication_id: uuid.UUID | None = None
    duplicate: bool = False


# --- Leads -----------------------------------------------------------------

# Simple format check (no email-validator dependency in this project) — good
# enough to reject obviously-malformed input like "not-an-email" or a blank
# string; not a substitute for actually verifying deliverability.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email_format(value: str) -> str:
    value = value.strip()
    if not value or not _EMAIL_RE.match(value):
        raise ValueError("Please enter a valid email address.")
    return value


class LeadCreate(BaseModel):
    company_name: str = Field(min_length=1, max_length=255)
    # Existing Account this Lead is associated with — optional (a Lead is
    # front-of-funnel and may not have one yet). When set, the UI is
    # expected to have already copied the relevant Account fields (company
    # name, industry, website, phone, address, country/state, annual
    # revenue, num employees, rating) onto this same payload; the server
    # only validates that the Account exists (see crm_service.create_lead()),
    # it does not itself copy fields from the Account.
    account_id: str | None = None
    salutation: str | None = Field(default=None, max_length=20)
    first_name: str | None = Field(default=None, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    title: str | None = Field(default=None, max_length=120)
    contact_email: str = Field(min_length=1, max_length=255, description="Required; must be a valid email address.")
    contact_phone: str | None = Field(default=None, max_length=50)
    mobile_phone: str | None = Field(default=None, max_length=50)
    # E.164 only (e.g. "+919876543210") — never Twilio's "whatsapp:"-prefixed
    # wire form; see services/whatsapp_service.py / integrations/twilio_whatsapp.py.
    whatsapp_number: str | None = Field(default=None, max_length=20)
    website: str | None = Field(default=None, max_length=255)
    linkedin_url: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=120)
    rating: str | None = Field(default=None, description="HOT | WARM | COLD")
    annual_revenue: float | None = None
    num_employees: int | None = None
    address: str | None = Field(default=None, max_length=500)
    country: str | None = Field(default=None, description="USA | Canada")
    state_province: str | None = Field(default=None, max_length=60)
    city: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    description: str | None = Field(default=None, max_length=2000)
    do_not_call: bool = False
    email_opt_out: bool = False
    campaign_id: uuid.UUID | None = None
    source: str | None = Field(default=None, max_length=120)
    owner_employee_id: uuid.UUID | None = None

    @field_validator("contact_email")
    @classmethod
    def _check_contact_email(cls, v: str) -> str:
        return _validate_email_format(v)

    @field_validator("contact_phone", "mobile_phone", "whatsapp_number")
    @classmethod
    def _clean_phone(cls, v: str | None) -> str | None:
        return normalize_phone(v)


class LeadUpdate(BaseModel):
    company_name: str | None = Field(default=None, min_length=1, max_length=255)
    account_id: str | None = None
    salutation: str | None = Field(default=None, max_length=20)
    first_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, min_length=1, max_length=120)
    title: str | None = Field(default=None, max_length=120)
    # Required overall on the Lead, so unlike other optional fields here this
    # one may be omitted (= "don't change it") but if present in the payload
    # must be a real, validly-formatted address — it can never be cleared
    # out to null/blank via update.
    contact_email: str | None = Field(default=None, min_length=1, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=50)
    mobile_phone: str | None = Field(default=None, max_length=50)
    whatsapp_number: str | None = Field(default=None, max_length=20)
    website: str | None = Field(default=None, max_length=255)
    linkedin_url: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=120)
    rating: str | None = Field(default=None, description="HOT | WARM | COLD")
    annual_revenue: float | None = None
    num_employees: int | None = None
    address: str | None = Field(default=None, max_length=500)
    country: str | None = Field(default=None, description="USA | Canada")
    state_province: str | None = Field(default=None, max_length=60)
    city: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    description: str | None = Field(default=None, max_length=2000)
    do_not_call: bool | None = None
    email_opt_out: bool | None = None
    source: str | None = Field(default=None, max_length=120)
    status: str | None = Field(default=None, description="lookup code, e.g. WORKING/QUALIFIED/DISQUALIFIED")
    owner_employee_id: uuid.UUID | None = None

    @field_validator("contact_email")
    @classmethod
    def _check_contact_email(cls, v: str | None) -> str | None:
        if v is None:
            raise ValueError("Email is required.")
        return _validate_email_format(v)

    @field_validator("contact_phone", "mobile_phone", "whatsapp_number")
    @classmethod
    def _clean_phone(cls, v: str | None) -> str | None:
        return normalize_phone(v)


class LeadOut(AuditOut):
    id: uuid.UUID
    campaign_id: uuid.UUID | None = None
    account_id: str | None = None
    # company_name/last_name are NOT NULL at create time (LeadCreate requires
    # them) — the Optional here is solely so FLS redaction (see
    # crm_service._redact()) can null them out in a response for a role
    # that can't see them; every other caller still gets a real value.
    company_name: str | None = None
    salutation: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    title: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    mobile_phone: str | None = None
    website: str | None = None
    linkedin_url: str | None = None
    industry: str | None = None
    rating: str | None = None
    annual_revenue: float | None = None
    num_employees: int | None = None
    address: str | None = None
    country: str | None = None
    state_province: str | None = None
    city: str | None = None
    postal_code: str | None = None
    # Never a stored column — always freshly derived from country +
    # state_province (see src/utils/geo.py:derive_region()) so it can never
    # drift out of sync with them. Read-only: not settable via
    # LeadCreate/LeadUpdate.
    region: str | None = None
    description: str | None = None
    do_not_call: bool | None = None
    email_opt_out: bool | None = None
    # WhatsApp — see Lead ORM's matching fields above for the field-by-field
    # rationale. whatsapp_number is a plain editable field, same treatment as
    # contact_phone/mobile_phone (see LeadCreate/LeadUpdate). The remaining
    # opt-in fields are read-only here for now — not yet accepted on
    # LeadCreate/LeadUpdate, since whatsapp_opt_in transitioning to True
    # needs opt_in_source/opt_in_at stamped alongside it, a write path this
    # first implementation doesn't build yet (see services/whatsapp_service.py).
    whatsapp_number: str | None = None
    whatsapp_opt_in: bool | None = None
    whatsapp_opt_in_source: str | None = None
    whatsapp_opt_in_at: datetime | None = None
    whatsapp_window_expires_at: datetime | None = None
    source: str | None = None
    status: str
    lead_score: int
    web_enrichment_points: int | None = None
    web_enrichment_summary: str | None = None
    web_enrichment_at: datetime | None = None
    signal_points: int | None = None
    owner_employee_id: uuid.UUID | None = None
    # Sales Territory/Region (see admin_models.Territory) — read-only, same
    # treatment as AccountOut.territory: never accepted on LeadCreate/
    # LeadUpdate, server-defaulted from the owner's Employee.territory_id.
    territory: str | None = None
    converted_account_id: str | None = None
    converted_contact_id: uuid.UUID | None = None
    converted_opportunity_id: str | None = None
    converted_at: datetime | None = None
    can_edit: bool = True
    can_delete: bool = True


class LeadConvertRequest(BaseModel):
    """Payload for POST /leads/{id}/convert — everything convert_lead() needs
    to create the Opportunity half of the Account+Contact+Opportunity trio
    (Account.legal_name and Contact.full_name/email come from the Lead
    itself, same as Salesforce deriving Account/Contact from Lead fields)."""
    opportunity_name: str = Field(min_length=1, max_length=255)
    estimated_value: float | None = None
    currency: str = Field(default="USD", max_length=3)
    expected_close_date: date | None = None


# --- Lead scoring ------------------------------------------------------------


class LeadScoringRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    field_name: str = Field(
        description="industry|annual_revenue|num_employees|rating|source|email_opt_out|do_not_call")
    operator: str = Field(description="EQUALS|GREATER_THAN|LESS_THAN|IS_SET|CONTAINS")
    comparison_value: str | None = Field(default=None, max_length=255)
    points: int


class LeadScoringRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    field_name: str | None = None
    operator: str | None = None
    comparison_value: str | None = Field(default=None, max_length=255)
    points: int | None = None
    is_active: bool | None = None


class LeadScoringRuleOut(AuditOut):
    id: uuid.UUID
    name: str
    field_name: str
    operator: str
    comparison_value: str | None = None
    points: int
    is_active: bool


class FieldPermissionEntry(BaseModel):
    """One (role, field) cell of the FLS matrix. `role_id` is a real
    `role.id`, never resolved to ADMIN (validated in the service layer —
    ADMIN can never be restricted). Used both as the admin save payload
    (role_id/object_name/field_name/visible/editable, id/audit fields
    ignored on the way in) and the admin read response (id/audit fields
    populated)."""
    id: uuid.UUID | None = None
    role_id: int
    object_name: str
    field_name: str
    visible: bool = True
    editable: bool = True


class FieldPermissionSaveRequest(BaseModel):
    object_name: str
    entries: list[FieldPermissionEntry]


class EffectiveFieldPermission(BaseModel):
    visible: bool
    editable: bool


class OrgWideDefaultEntry(BaseModel):
    """One (object, access_level) cell of the OWD matrix."""
    object_name: str
    access_level: str = Field(description="PRIVATE|PUBLIC_READ_ONLY|PUBLIC_READ_WRITE")


class OrgWideDefaultsOut(BaseModel):
    """GET /admin/org-wide-defaults response — always exactly the 5 seeded
    rows (LEAD/ACCOUNT/CONTACT/OPPORTUNITY/CAMPAIGN), keyed by object_name
    for easy lookup."""
    defaults: dict[str, str]


class OrgWideDefaultsSaveRequest(BaseModel):
    """PUT /admin/org-wide-defaults payload — full replace, same reasoning as
    FieldPermissionSaveRequest: only 5 keys ever exist, so every save must
    submit the complete set (no partial-update ambiguity)."""
    entries: list[OrgWideDefaultEntry]


class RecordShareCreate(BaseModel):
    """Payload for POST /record-shares — grants shared_with_employee_id
    READ or EDIT on one specific record. Never DELETE (see
    models.enums.RecordAccessLevel / RecordShare's docstring) and never a
    team/role — user-only, by design."""
    object_name: str = Field(description="LEAD|ACCOUNT|CONTACT|OPPORTUNITY|CAMPAIGN")
    record_id: str
    shared_with_employee_id: uuid.UUID
    access_level: str = Field(description="READ|EDIT")


class RecordShareOut(AuditOut):
    id: uuid.UUID
    object_name: str
    record_id: str
    shared_with_employee_id: uuid.UUID
    access_level: str
    granted_by: uuid.UUID | None = None
    granted_at: datetime


class LeadScoreBreakdownEntry(BaseModel):
    """One active rule that currently matches a given lead's fields — the
    transparency view behind Lead.lead_score, computed live rather than
    stored (see crm_service.get_lead_score_breakdown())."""
    rule_id: uuid.UUID
    name: str
    points: int


# --- Product catalog (what we sell — for AI drafting to match against) ------


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=2000)
    target_industry: str | None = Field(default=None, max_length=120)


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    target_industry: str | None = Field(default=None, max_length=120)
    is_active: bool | None = None


class ProductOut(AuditOut):
    id: uuid.UUID
    name: str
    description: str
    target_industry: str | None = None
    is_active: bool


# --- Sales Cadence -------------------------------------------------------------


class CadenceStepCreate(BaseModel):
    step_order: int = Field(ge=1)
    step_type: str = Field(description="CALL|EMAIL|LINKEDIN|TASK|BREAK|FOLLOW_UP|OTHER")
    subject: str = Field(min_length=1, max_length=255)
    instructions: str | None = Field(default=None, max_length=2000)
    wait_days: int = Field(ge=0)
    skip_weekends: bool = Field(
        default=False, description="If true, wait_days counts Mon-Fri business days only.")


class CadenceStepUpdate(BaseModel):
    step_order: int | None = Field(default=None, ge=1)
    step_type: str | None = None
    subject: str | None = Field(default=None, min_length=1, max_length=255)
    instructions: str | None = Field(default=None, max_length=2000)
    wait_days: int | None = Field(default=None, ge=0)
    skip_weekends: bool | None = None


class CadenceStepOut(AuditOut):
    id: uuid.UUID
    cadence_template_id: uuid.UUID
    step_order: int
    step_type: str
    subject: str
    instructions: str | None = None
    wait_days: int
    skip_weekends: bool


class CadenceTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class CadenceTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None


class CadenceTemplateOut(AuditOut):
    id: uuid.UUID
    name: str
    description: str | None = None
    is_active: bool
    steps: list[CadenceStepOut] = []


class LeadCadenceEnrollRequest(BaseModel):
    cadence_template_id: uuid.UUID


class LeadCadenceEnrollmentOut(AuditOut):
    id: uuid.UUID
    lead_id: uuid.UUID
    cadence_template_id: uuid.UUID
    status: str
    current_step_order: int
    enrolled_at: datetime
    completed_at: datetime | None = None
    enrolled_by: uuid.UUID | None = None


class CadenceTaskCompleteRequest(BaseModel):
    outcome_status: str = Field(description="DONE|SKIPPED")
    notes: str | None = Field(default=None, max_length=2000)


class CadenceTaskOut(AuditOut):
    id: uuid.UUID
    enrollment_id: uuid.UUID
    cadence_step_id: uuid.UUID
    lead_id: uuid.UUID
    step_type: str
    subject: str
    due_date: date
    status: str
    completed_at: datetime | None = None
    notes: str | None = None
    auto_resolved: bool = False


class LeadCadenceEnrollmentDetailOut(BaseModel):
    """GET /leads/{id}/cadence response for the Lead detail page's Cadence panel."""
    enrollment: LeadCadenceEnrollmentOut
    tasks: list[CadenceTaskOut]


class CadenceSchedulerRunOut(BaseModel):
    """Response for POST /cadence/advance-due-steps (see
    require_cadence_scheduler_secret / crm_service.advance_due_cadence_steps())
    — one run's tally, for scheduler job logs/alerting."""
    breaks_resolved: int
    follow_ups_skipped: int
    follow_ups_left_pending: int
    enrollments_completed: int


# --- AI-assisted email drafting & call prep (BRD §5.6/§5.7) -----------------


class EmailDraftOut(BaseModel):
    subject: str
    body: str
    model: str
    grounded_in_replies: int = Field(
        description="How many past-replied emails in this lead's industry informed the draft (0 if none found).")
    matched_products: list[str] = Field(
        default_factory=list, description="Our active product(s)/service(s) this draft was built around.")


class CallPrepOut(BaseModel):
    talking_points: list[str]
    likely_objections: list[str]
    opening_line: str
    model: str
    matched_products: list[str] = Field(
        default_factory=list, description="Our active product(s)/service(s) this call prep was built around.")


class LeadWebEnrichmentOut(BaseModel):
    """Response for POST /leads/{id}/web-enrichment (BRD SC-2) — also
    persisted onto the Lead itself (web_enrichment_* fields on LeadOut) so a
    later GET doesn't need to re-run this to see the last result.

    No live web search backs this (Cohere retired their hosted web-search
    connector — see services/llm_client.py) — the model reasons from the
    lead's own fields plus whatever it already knows about well-known
    companies, under an explicit "say unknown rather than invent" prompt
    instruction, so headlines/summary here are a best-effort signal, not a
    verified news feed."""
    funding_signal: bool
    hiring_signal: bool
    growth_signal: bool
    headlines: list[str]
    score_points: int = Field(description="0-30 — how strong a buying-intent signal the findings are")
    summary: str
    lead_score: int = Field(description="The lead's total score after combining this with the rule-based score")
    model: str


# --- Pulse: signal sourcing, Radar worklist, next-best-action ---------------
# Grounded in verified external Signal rows (crm_models.Signal), unlike the
# web-enrichment above — see crm_service.py's Pulse section for the scoring/
# sourcing logic these wrap.


class SignalOut(BaseModel):
    id: uuid.UUID
    lead_id: uuid.UUID | None = None
    company_name: str
    type: str = Field(description="see models.enums.SignalType")
    source: str
    summary: str
    strength: float = Field(description="0..1 raw signal confidence before time-decay")
    practice_hint: str | None = None
    url: str | None = None
    captured_at: datetime
    score_points: int = Field(description="Decayed 0..40 contribution this signal makes to the lead score right now")


class RadarRow(BaseModel):
    lead_id: uuid.UUID
    company_name: str
    industry: str | None = None
    annual_revenue: float | None = None
    status: str
    lead_score: int
    grade: str = Field(description="A/B/C/D band derived from lead_score")
    signal_points: int
    recommended_practice: str | None = None
    why_now: str
    top_signal: str | None = Field(default=None, description="SignalType of the lead's freshest/strongest signal")
    top_signal_age_days: int | None = None
    signal_count: int
    owner_employee_id: uuid.UUID | None = None


class NextBestActionOut(BaseModel):
    lead_id: uuid.UUID
    action: str
    channel: str = Field(description="see models.enums.LeadCommunicationChannel (EMAIL|CALL|LINKEDIN)")
    why_now: str
    due_in_days: int
    recommended_practice: str | None = None
    suggested_cadence_template_id: uuid.UUID | None = None
    source: str = Field(description='"ai" when the LLM produced it, "fallback" when derived deterministically')


class SignalIngestResult(BaseModel):
    sources_run: list[str]
    signals_ingested: int
    leads_created: int
    leads_updated: int
    rescored: int
