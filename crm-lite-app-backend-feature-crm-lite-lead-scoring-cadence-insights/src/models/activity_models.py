"""Models for the Activity module (§1/§11 of the API spec) — Communications,
Notifications, Audit log.

Full ORM schema implemented (the central "database logic" every developer
builds their service/route layer on top of) — business logic itself
(append-only communications, system-only notification creation, server-side
audit writes on every mutation) is NOT here; see services/activity_service.py
for what still needs to be written, and repositories/activity_repository.py
for the ready-to-use data-access classes.

Tables owned: communication, notification, audit_log. Communications hang off
an account and/or an agreement (both are rows in the same `communication`
table); notifications are system-generated only (never created directly via
API — see §13's scheduled jobs); audit_log rows are written server-side on
every mutation across every module, not via a public POST, so AuditLog
intentionally does NOT carry the audit/soft-delete mixins other entities do —
an audit trail row is immutable and never itself soft-deleted.
"""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import AuditMixin, Base, SoftDeleteMixin
from src.models.common import AuditOut, ORMModel


class CallDisposition(Base):
    """Admin-configurable lookup for Communication.call_disposition_id — same
    shape/role as crm_models.AccountType: managed via the generic
    /admin/lookups/call_disposition endpoints (admin_service._LOOKUP_TABLES),
    seeded with the well-known default set (models.enums.CallOutcome) but not
    limited to it — an admin can add/rename/retire dispositions without a
    code change."""
    __tablename__ = "call_disposition"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))


class WhatsAppTemplate(Base, AuditMixin, SoftDeleteMixin):
    """A Twilio Content Template approved for WhatsApp session-starting
    (outside the 24-hour customer-service window) sends — see
    services/whatsapp_service.py. Unlike CallDisposition/other lookup
    tables, templates are not admin-editable free-form reference data: each
    row mirrors a real Content Template registered with WhatsApp/Twilio
    (content_sid, e.g. "HXxxxxxxxx") and must not be assumed approved just
    because a row exists here — only approval_status == APPROVED and
    is_active == True templates may ever be sent (enforced in
    whatsapp_service.py, not just by hiding others in the UI)."""
    __tablename__ = "whatsapp_template"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    content_sid: Mapped[str] = mapped_column(String(64), unique=True)
    language: Mapped[str] = mapped_column(String(10), default="en")
    category: Mapped[str] = mapped_column(String(20))  # UTILITY | MARKETING | AUTHENTICATION
    body_preview: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    variable_count: Mapped[int] = mapped_column(default=0)
    # PENDING (default) | APPROVED | REJECTED — WhatsApp/Twilio's own
    # template review status, mirrored here so whatsapp_service.py never has
    # to call out to Twilio just to check whether a template may be used.
    approval_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Communication(Base, AuditMixin, SoftDeleteMixin):
    """Also the backing store for a Lead's Email/Call Insights (lead_id set,
    account_id/agreement_id null) — see crm_service.complete_cadence_task(),
    which auto-logs one of these when a CALL/EMAIL cadence step is completed,
    and activity_service.get_lead_email_insights()/get_lead_call_insights(),
    which aggregate over them. opened_at/replied_at are set after the fact by
    activity_service.mark_communication_opened()/mark_communication_replied()
    — there's no live mailbox integration here, so these are populated either
    by a rep marking a logged email as opened/replied, or by whatever mail
    provider webhook is wired up later calling the same endpoint."""
    __tablename__ = "communication"
    __table_args__ = (
        CheckConstraint(
            "account_id IS NOT NULL OR agreement_id IS NOT NULL OR lead_id IS NOT NULL",
            name="ck_communication_account_or_agreement_or_lead",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("account.id"), nullable=True)
    agreement_id: Mapped[str | None] = mapped_column(ForeignKey("agreement.id"), nullable=True)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("lead.id"), nullable=True)
    received_via_team_id: Mapped[int | None] = mapped_column(ForeignKey("team.id"), nullable=True)
    direction: Mapped[str] = mapped_column(String(10))  # INBOUND | OUTBOUND
    channel: Mapped[str] = mapped_column(String(30))
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Full message content — for EMAIL rows, the email body (both directions,
    # so a rep can open a logged email and read what was actually sent/
    # received, not just the subject); for CALL rows, free-text notes taken
    # about the call, kept separate from `subject` (see add_lead_communication
    # in activity_service.py).
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    from_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    to_recipients: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    cc_recipients: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    graph_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Twilio's message SID for an SMS row (see services/sms_service.py) — kept
    # separate from graph_message_id above (that one's Microsoft Graph's inbound
    # email id) so a later delivery-status lookup against Twilio's API has
    # something to key off.
    provider_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str | None] = mapped_column(String(30), nullable=True)
    call_duration_seconds: Mapped[int | None] = mapped_column(nullable=True)
    call_disposition_id: Mapped[int | None] = mapped_column(ForeignKey("call_disposition.id"), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # WhatsApp status-callback tracking (see services/whatsapp_service.py /
    # webhook.status route) — no prior delivery-status tracking existed on
    # this table (Twilio SMS status callbacks were never wired up), so this
    # is new ground, kept generic enough (queued/sent/delivered/read/failed/
    # undelivered) that a future SMS status callback could reuse it too.
    # failure_code stores Twilio's numeric error code as a string (e.g.
    # "63016") — a code, not a quantity, so never a numeric column type.
    delivery_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    whatsapp_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("whatsapp_template.id"), nullable=True)
    # JSON-encoded dict of the template's variable substitutions (e.g.
    # {"1": "Priya", "2": "the Q3 proposal"}) — a plain Text column holding
    # a JSON string, matching this project's existing convention of no
    # native JSON/JSONB column type anywhere; (de)serialized in the service
    # layer. Only ever set alongside whatsapp_template_id.
    template_variables: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Twilio-hosted media URL/content-type for inbound or outbound WhatsApp
    # media (Twilio's MediaUrlN/MediaContentTypeN) — stored as a reference
    # only, same treatment as OpportunityDocument.sharepoint_url elsewhere in
    # this codebase, since there is no object/file storage abstraction here
    # to download and persist the bytes into, and Twilio-hosted media URLs
    # are not guaranteed to remain available indefinitely.
    media_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    media_content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    logged_by_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True)

    account: Mapped["Account | None"] = relationship()  # noqa: F821 (crm_models.Account)
    agreement: Mapped["Agreement | None"] = relationship()  # noqa: F821 (contracts_models.Agreement)
    lead: Mapped["Lead | None"] = relationship()  # noqa: F821 (crm_models.Lead)
    call_disposition: Mapped["CallDisposition | None"] = relationship()
    whatsapp_template: Mapped["WhatsAppTemplate | None"] = relationship()


class Notification(Base, AuditMixin, SoftDeleteMixin):
    __tablename__ = "notification"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agreement_id: Mapped[str | None] = mapped_column(ForeignKey("agreement.id"), nullable=True)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("account.id"), nullable=True)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead.id"), nullable=True)
    recipient_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True)
    notification_type: Mapped[str] = mapped_column(String(50))  # incl. BUDGET_THRESHOLD
    severity: Mapped[str] = mapped_column(String(20))
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(30))
    field_changed: Mapped[str | None] = mapped_column(String(120), nullable=True)
    old_value: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    new_value: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    performed_by_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True)
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- request/response (Pydantic) schemas ------------------------------------


class CommunicationCreate(BaseModel):
    direction: str = Field(description="INBOUND | OUTBOUND")
    channel: str = Field(max_length=30)
    subject: str | None = Field(default=None, max_length=500)
    body: str | None = Field(default=None, description="Email body, or free-text call notes.")
    notes: str | None = Field(default=None, description="Free-text notes, kept separate from subject/body.")
    from_address: str | None = Field(default=None, max_length=255)
    to_recipients: str | None = Field(default=None, max_length=2000)
    cc_recipients: str | None = Field(default=None, max_length=2000)
    graph_message_id: str | None = Field(default=None, max_length=255)
    provider_message_id: str | None = Field(default=None, max_length=64)
    occurred_at: datetime
    source: str | None = Field(default=None, max_length=30)
    received_via_team_id: int | None = None
    call_duration_seconds: int | None = Field(default=None, ge=0)
    call_outcome: str | None = Field(
        default=None,
        description="Code from the call_disposition lookup (admin-configurable via "
                    "/admin/lookups/call_disposition) — CONNECTED|VOICEMAIL|NO_ANSWER|"
                    "BUSY|WRONG_NUMBER|OTHER out of the box.")


class CommunicationOut(AuditOut):
    id: uuid.UUID
    account_id: str | None = None
    agreement_id: str | None = None
    lead_id: uuid.UUID | None = None
    received_via_team_id: int | None = None
    direction: str
    channel: str
    subject: str | None = None
    body: str | None = None
    notes: str | None = None
    from_address: str | None = None
    to_recipients: str | None = None
    cc_recipients: str | None = None
    graph_message_id: str | None = None
    provider_message_id: str | None = None
    occurred_at: datetime
    source: str | None = None
    call_duration_seconds: int | None = None
    call_outcome: str | None = None
    opened_at: datetime | None = None
    replied_at: datetime | None = None
    delivery_status: str | None = None
    failure_code: str | None = None
    whatsapp_template_id: uuid.UUID | None = None
    template_variables: str | None = None
    media_url: str | None = None
    media_content_type: str | None = None
    logged_by_employee_id: uuid.UUID | None = None


class VoiceAccessTokenOut(BaseModel):
    """Response for GET /leads/{id}/voice-token — a short-lived Twilio
    Voice Access Token the browser's Voice SDK uses to place a call; never
    a Twilio credential itself (see integrations/twilio_voice.py)."""
    token: str
    identity: str


class UpdateCallNotesRequest(BaseModel):
    """Payload for POST /leads/{id}/communications/{comm_id}/call-notes —
    the only two fields a rep may still edit on a CALL Communication row
    once a real Dial Pad call has set its Outcome/Duration from Twilio
    (see services/voice_service.update_call_notes()). Both optional/
    exclude-unset so touching one never blanks out the other."""
    subject: str | None = Field(default=None, max_length=500)
    notes: str | None = None


class WhatsAppTemplateOut(AuditOut):
    id: uuid.UUID
    name: str
    content_sid: str
    language: str
    category: str
    body_preview: str | None = None
    variable_count: int
    approval_status: str
    is_active: bool


class SendEmailRequest(BaseModel):
    """Payload for POST /leads/{id}/communications/send — actually sends the
    (possibly AI-drafted, possibly hand-edited) email and logs it as a
    Communication on success. to_address defaults to the lead's own
    contact_email when omitted."""
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1)
    to_address: str | None = Field(default=None, max_length=255)


class SendSmsRequest(BaseModel):
    """Payload for POST /leads/{id}/sms — actually sends the text via Twilio
    and logs it as a Communication on success, mirroring SendEmailRequest.
    1600 chars is Twilio's practical cap for a single send before it's
    silently split into multiple billed segments — reject that here instead
    of letting Twilio be the first thing to do so."""
    message: str = Field(min_length=1, max_length=1600)


class SendWhatsAppRequest(BaseModel):
    """Payload for POST /leads/{id}/whatsapp — exactly one of:
    - `body`: a free-form message (mirrors SendSmsRequest; same 1600-char
      practical cap). WhatsApp only allows this inside the lead's 24-hour
      customer-service window.
    - `template_id`: an approved whatsapp_template row (see
      GET /whatsapp/templates), with `template_variables` filling its
      {{1}}, {{2}}... placeholders, e.g. {"1": "Priya"}. Works any time."""
    body: str | None = Field(default=None, min_length=1, max_length=1600)
    template_id: uuid.UUID | None = None
    template_variables: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _body_xor_template(self):
        if (self.body is None) == (self.template_id is None):
            raise ValueError("Provide exactly one of 'body' or 'template_id'.")
        if self.template_variables and self.template_id is None:
            raise ValueError("'template_variables' is only allowed with 'template_id'.")
        return self


class WhatsAppIntakeResult(BaseModel):
    """Response for POST /whatsapp/webhook/inbound — mirrors
    crm_models.SmsIntakeResult exactly (one Twilio webhook call is exactly
    one inbound WhatsApp message). Unmatched senders are not logged against
    any record, same as inbound SMS: matched_lead=False is the signal that
    a Lead with that whatsapp_number needs to be created/updated by hand."""
    matched_lead: bool
    lead_id: uuid.UUID | None = None
    communication_id: uuid.UUID | None = None
    duplicate: bool = False


class CommunicationTrackEvent(BaseModel):
    """Payload for POST .../opened and .../replied — occurred_at defaults to
    now if omitted (the common case: a rep marking it after the fact), but
    can be backdated to when a mail-provider webhook says the event actually
    happened."""
    occurred_at: datetime | None = None


class LeadEmailInsightsOut(BaseModel):
    total_emails: int
    inbound_count: int
    outbound_count: int
    opened_count: int
    replied_count: int
    open_rate_percent: float | None = None
    reply_rate_percent: float | None = None
    last_email_at: datetime | None = None


class LeadCallInsightsOut(BaseModel):
    total_calls: int
    connected_count: int
    connected_rate_percent: float | None = None
    avg_duration_seconds: float | None = None
    last_call_at: datetime | None = None
    outcome_breakdown: dict[str, int] = {}


class NotificationOut(AuditOut):
    id: uuid.UUID
    agreement_id: str | None = None
    account_id: str | None = None
    lead_id: uuid.UUID | None = None
    recipient_employee_id: uuid.UUID | None = None
    notification_type: str
    severity: str
    message: str | None = None
    sent_at: datetime
    acknowledged: bool


class AuditLogOut(ORMModel):
    id: uuid.UUID
    entity_type: str
    entity_id: str
    action: str
    field_changed: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    performed_by_employee_id: uuid.UUID | None = None
    performed_at: datetime
