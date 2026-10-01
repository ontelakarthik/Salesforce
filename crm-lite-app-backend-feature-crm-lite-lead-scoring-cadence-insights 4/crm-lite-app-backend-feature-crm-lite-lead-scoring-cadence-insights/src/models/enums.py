"""Shared enumerations (4-role model + business statuses/types). Skeleton.

Lives under models/ (not a separate schemas/ package) — see models/common.py.
"""
from enum import Enum


class Role(str, Enum):
    SALES = "SALES"
    ACCOUNT_EXEC = "ACCOUNT_EXEC"
    LEADERSHIP = "LEADERSHIP"
    ADMIN = "ADMIN"


class AccessState(str, Enum):
    ACTIVE = "ACTIVE"
    NO_ROLE = "NO_ROLE"
    INACTIVE = "INACTIVE"


class AccountType(str, Enum):
    PROSPECT = "PROSPECT"
    CLIENT = "CLIENT"
    VENDOR = "VENDOR"
    PARTNER = "PARTNER"


class OpportunityStage(str, Enum):
    NEW = "NEW"
    QUALIFIED = "QUALIFIED"
    PROPOSAL = "PROPOSAL"
    NEGOTIATION = "NEGOTIATION"
    WON = "WON"
    LOST = "LOST"


class AgreementType(str, Enum):
    NDA = "NDA"
    MSA = "MSA"
    SOW = "SOW"
    VENDOR_MSA = "VENDOR_MSA"
    PURCHASE_ORDER = "PURCHASE_ORDER"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    REVIEW = "REVIEW"
    APPROVED = "APPROVED"
    SENT = "SENT"
    SIGNED = "SIGNED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class TimesheetStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class LeadStatus(str, Enum):
    """Front-of-funnel status, ahead of Account/Opportunity even existing —
    mirrors TimesheetStatus's pattern (plain string column + this enum,
    transitions validated in the service layer) rather than a lookup table,
    since these values aren't admin-customizable reference data.

    The main path is NEW -> ATTEMPTING_CONTACT -> CONTACTED -> QUALIFYING ->
    QUALIFIED -> CONVERTED (via convert_lead(), not a plain status PATCH).
    NURTURING/UNQUALIFIED/DISQUALIFIED are exits reachable from most stages
    along the way — see crm_service._LEAD_TRANSITIONS for the exact legal
    moves. Replaces the old flat NEW/WORKING/QUALIFIED/CONVERTED/
    DISQUALIFIED set; existing WORKING rows are migrated to
    ATTEMPTING_CONTACT (see the alembic revision that introduced this)."""
    NEW = "NEW"
    ATTEMPTING_CONTACT = "ATTEMPTING_CONTACT"
    CONTACTED = "CONTACTED"
    QUALIFYING = "QUALIFYING"
    QUALIFIED = "QUALIFIED"
    NURTURING = "NURTURING"
    UNQUALIFIED = "UNQUALIFIED"
    DISQUALIFIED = "DISQUALIFIED"
    CONVERTED = "CONVERTED"


class LeadScoringOperator(str, Enum):
    """Vocabulary for LeadScoringRule.operator — code-level behavior, not
    admin-editable reference data (the rule *rows* are admin-editable, this
    enum of comparison kinds is not)."""
    EQUALS = "EQUALS"
    GREATER_THAN = "GREATER_THAN"
    LESS_THAN = "LESS_THAN"
    IS_SET = "IS_SET"
    CONTAINS = "CONTAINS"


class CadenceStepType(str, Enum):
    CALL = "CALL"
    EMAIL = "EMAIL"
    LINKEDIN = "LINKEDIN"
    TASK = "TASK"
    #: A pure waiting period — no outreach happens, no Communication is
    #: logged. The scheduler (crm_service.advance_due_cadence_steps())
    #: auto-resolves a due BREAK task itself; a rep never has to act on one.
    BREAK = "BREAK"
    #: A real outreach step, same as CALL/EMAIL/LINKEDIN, EXCEPT the
    #: scheduler auto-skips it the moment it comes due if the lead has
    #: already replied since the previous step — see
    #: crm_service.advance_due_cadence_steps(). If there's no reply yet, a
    #: rep completes it manually like any other step.
    FOLLOW_UP = "FOLLOW_UP"
    OTHER = "OTHER"


class LeadCommunicationChannel(str, Enum):
    """Allow-list for Lead-level Communication.channel — kept small and
    deterministic so email-insights/call-insights aggregation can group on
    it reliably (unlike Account/Agreement communications, whose `channel` is
    free text)."""
    EMAIL = "EMAIL"
    CALL = "CALL"
    LINKEDIN = "LINKEDIN"
    MEETING = "MEETING"
    SMS = "SMS"
    WHATSAPP = "WHATSAPP"
    OTHER = "OTHER"


class SignalType(str, Enum):
    """Vocabulary for Signal.type (Pulse — see crm_models.Signal /
    crm_service's Pulse functions). A fixed, small set rather than free text
    so Radar can group/label consistently, same reasoning as
    LeadCommunicationChannel above."""
    HIRING = "HIRING"
    RFP_TENDER = "RFP_TENDER"
    TECH_STACK = "TECH_STACK"
    BUYER_INTENT = "BUYER_INTENT"
    LEADERSHIP_MOVE = "LEADERSHIP_MOVE"
    FUNDING_MA = "FUNDING_MA"
    FILING_EARNINGS = "FILING_EARNINGS"
    WEB_EVENT = "WEB_EVENT"


class CallOutcome(str, Enum):
    CONNECTED = "CONNECTED"
    VOICEMAIL = "VOICEMAIL"
    NO_ANSWER = "NO_ANSWER"
    BUSY = "BUSY"
    WRONG_NUMBER = "WRONG_NUMBER"
    OTHER = "OTHER"


class LeadCadenceEnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CadenceTaskStatus(str, Enum):
    """Plain string column + this enum, transitions validated in the service
    layer (mirrors LeadStatus/TimesheetStatus) — not admin-customizable
    reference data."""
    PENDING = "PENDING"
    DONE = "DONE"
    SKIPPED = "SKIPPED"


class RecordAccessLevel(str, Enum):
    """The three access checks services.record_access_service.
    can_user_access_record() answers. RecordShare.access_level (see
    crm_models.py) only ever persists READ or EDIT — DELETE is deliberately
    never grantable via sharing, only via ownership/records.see_all plus
    the object's own existing delete capability."""
    READ = "READ"
    EDIT = "EDIT"
    DELETE = "DELETE"


class OrgWideDefaultAccessLevel(str, Enum):
    """Vocabulary for OrgWideDefault.access_level (see crm_models.py) — the
    per-object row-visibility baseline (Salesforce OWD-style), applied
    underneath row ownership/role-hierarchy/records.see_all — see
    crm_service._in_read_scope()/_in_write_scope(). PRIVATE reproduces
    today's ownership-only behavior exactly."""
    PRIVATE = "PRIVATE"
    PUBLIC_READ_ONLY = "PUBLIC_READ_ONLY"
    PUBLIC_READ_WRITE = "PUBLIC_READ_WRITE"
