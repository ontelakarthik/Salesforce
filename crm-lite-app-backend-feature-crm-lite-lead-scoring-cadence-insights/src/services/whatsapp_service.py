"""WhatsApp messaging business logic (Twilio WhatsApp) — a fourth
Communication channel alongside logged calls, sent emails and SMS (see
services/sms_service.py, activity_service.send_lead_sms()). No separate
WhatsApp table: every message, inbound or outbound, is a row in the same
`communication` table (see models/activity_models.py), same as SMS.

Twilio HTTP calls themselves live in src/integrations/twilio_whatsapp.py —
this module only does Lead lookup/access, minimal 24-hour-window
bookkeeping, and Communication persistence:
- send_lead_whatsapp() mirrors activity_service.send_lead_sms()'s shape for
  the outbound (authenticated, JWT'd employee) path.
- process_inbound_whatsapp() mirrors crm_service.process_inbound_sms()'s
  shape for the inbound (Twilio webhook) path.
- process_whatsapp_status_callback() is new ground (no prior Twilio SMS
  status callback was ever wired up in this project) but follows the same
  idempotent-lookup-by-provider_message_id shape as the other two.

- list_whatsapp_templates()/sync_whatsapp_templates() manage the approved
  Content Templates a closed-window send has to use (WhatsApp only allows
  free-form messages inside the lead's 24-hour customer-service window).

There is no opt-in/consent flag beyond a Lead simply having a
whatsapp_number on file.
"""
import json
from datetime import datetime, timedelta, timezone

from src.integrations.twilio_whatsapp import WhatsAppSender, WhatsAppTemplateSource
from src.models import activity_models
from src.models.enums import LeadCommunicationChannel
from src.repositories.activity_repository import CommunicationRepository, WhatsAppTemplateRepository
from src.repositories.crm_repository import LeadRepository
from src.services.activity_service import _communication_out
from src.services.admin_service import verified_employee_uuid
from src.utils.error_handling import handle_errors
from src.utils.exceptions import DomainError
from src.utils.scope import require_lead_scope
from src.utils.security import CurrentUser

_WHATSAPP_WINDOW = timedelta(hours=24)

#: Stamped as created_by/updated_by on Communication rows the inbound
#: webhook creates and the status callback updates — mirrors
#: crm_service._SMS_INTAKE_USER_ID; there's no logged-in CurrentUser for a
#: request Twilio itself makes.
_WHATSAPP_INTAKE_USER_ID = "whatsapp-intake"

_DELIVERY_STATUSES = {"queued", "sent", "delivered", "read", "failed", "undelivered"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


@handle_errors("send lead whatsapp message")
def send_lead_whatsapp(user: CurrentUser, lead_repo: LeadRepository, comm_repo: CommunicationRepository,
                       template_repo: WhatsAppTemplateRepository, whatsapp_sender: WhatsAppSender, lid,
                       payload: activity_models.SendWhatsAppRequest,
                       ) -> activity_models.CommunicationOut:
    """The WhatsApp action on a Lead's Activity tab: delivers via
    whatsapp_sender, then logs it as a Communication on success — mirrors
    activity_service.send_lead_sms(), just with Twilio's WhatsApp channel in
    place of SMS.

    Recipient resolution: whatsapp_number first, falling back to
    contact_phone then mobile_phone (same fallback order send_lead_sms()
    uses) when whatsapp_number isn't on file. This intentionally sends
    WhatsApp messages to numbers that were never through the
    whatsapp_opt_in flow — a deliberate product choice made despite that,
    not an oversight; revisit if Twilio/Meta's WhatsApp Business Policy
    enforcement on this account becomes a problem.

    Two send paths (see SendWhatsAppRequest):
    - template_id: an APPROVED + active whatsapp_template, re-checked here
      rather than trusting the caller picked from GET /whatsapp/templates.
      The logged Communication.body is the template's preview with the
      variables filled in, so the Activity tab shows what the lead read.
    - body: free-form. Not blocked up front when whatsapp_window_expires_at
      says the window is closed — that field is only refreshed by inbound
      webhooks matched on whatsapp_number, so it can be missing even when
      Twilio would accept the send. Twilio stays the source of truth; if it
      rejects a free-form send while our window looks closed, the error is
      re-raised as WHATSAPP_TEMPLATE_REQUIRED so the UI can steer the rep
      to a template.
    """
    lead = lead_repo.get(lid)
    if lead is None:
        raise DomainError("LEAD_NOT_FOUND", f"No lead '{lid}'.", 404)
    require_lead_scope(user, lead_repo, lid, for_write=True)
    to_number = lead.whatsapp_number or lead.contact_phone or lead.mobile_phone
    if not to_number:
        raise DomainError(
            "WHATSAPP_RECIPIENT_MISSING",
            "This lead has no whatsapp_number, contact_phone, or mobile_phone on file.", 422)

    template_fields = {}
    if payload.template_id is not None:
        template = _get_sendable_template(template_repo, payload.template_id)
        variables = _checked_template_variables(template, payload.template_variables)
        provider_message_id = whatsapp_sender.send_template(to_number, template.content_sid, variables)
        body = _render_template(template, variables)
        template_fields = {"whatsapp_template_id": template.id,
                           "template_variables": json.dumps(variables) if variables else None}
    else:
        body = payload.body
        try:
            provider_message_id = whatsapp_sender.send(to_number, body)
        except DomainError as exc:
            if _window_open(lead):
                raise
            raise DomainError(
                "WHATSAPP_TEMPLATE_REQUIRED",
                f"{exc.message} — this lead hasn't messaged your WhatsApp number in the last 24 hours, "
                "so WhatsApp only allows an approved template. Choose a template instead.", 422) from exc

    row = comm_repo.create(
        lead_id=lid, account_id=None, agreement_id=None,
        direction="OUTBOUND", channel=LeadCommunicationChannel.WHATSAPP.value,
        body=body, to_recipients=to_number, occurred_at=_now(),
        source="SENT", provider_message_id=provider_message_id,
        logged_by_employee_id=verified_employee_uuid(user),
        created_by=user.employee_id, updated_by=user.employee_id,
        **template_fields,
    )
    return _communication_out(row)


def _window_open(lead) -> bool:
    return lead.whatsapp_window_expires_at is not None and lead.whatsapp_window_expires_at > _now()


def _get_sendable_template(template_repo: WhatsAppTemplateRepository, template_id):
    template = template_repo.get(template_id)
    if template is None:
        raise DomainError("WHATSAPP_TEMPLATE_NOT_FOUND", f"No WhatsApp template '{template_id}'.", 404)
    if template.approval_status != "APPROVED" or not template.is_active:
        raise DomainError(
            "WHATSAPP_TEMPLATE_NOT_SENDABLE",
            f"WhatsApp template '{template.name}' is {template.approval_status}"
            f"{'' if template.is_active else ' and inactive'} — only approved, active templates can be sent.",
            422)
    return template


def _checked_template_variables(template, variables: dict[str, str]) -> dict[str, str]:
    """Every {{1}}..{{variable_count}} must be given and non-blank, and
    nothing else — otherwise the lead would receive a literal "{{2}}"."""
    expected = {str(i) for i in range(1, template.variable_count + 1)}
    blank = [k for k, v in variables.items() if not v.strip()]
    if set(variables) != expected or blank:
        raise DomainError(
            "WHATSAPP_TEMPLATE_VARIABLES_INVALID",
            f"WhatsApp template '{template.name}' needs exactly these non-blank variables: "
            f"{sorted(expected, key=int) or 'none'}; got {sorted(variables) or 'none'}.", 422)
    return variables


def _render_template(template, variables: dict[str, str]) -> str:
    if not template.body_preview:
        return f"[WhatsApp template: {template.name}]"
    rendered = template.body_preview
    for key, value in variables.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered


def list_whatsapp_templates(template_repo: WhatsAppTemplateRepository) -> list[activity_models.WhatsAppTemplateOut]:
    """The templates the WhatsApp dialog may offer — approved + active only."""
    rows = sorted(template_repo.list_approved_active(), key=lambda t: t.name.lower())
    return [activity_models.WhatsAppTemplateOut.model_validate(r) for r in rows]


@handle_errors("sync whatsapp templates")
def sync_whatsapp_templates(user: CurrentUser, template_repo: WhatsAppTemplateRepository,
                            source: WhatsAppTemplateSource) -> list[activity_models.WhatsAppTemplateOut]:
    """Mirrors the Twilio account's Content Templates into whatsapp_template:
    new ones are created, existing ones (matched on content_sid) get their
    name/body/approval status refreshed, and ones no longer on Twilio are
    deactivated rather than deleted, since past Communication rows still
    reference them. Returns every template, not just approved ones, so an
    admin can see what is still pending/rejected."""
    fetched = source.fetch_templates()
    existing = {t.content_sid: t for t in template_repo.list()}
    for f in fetched:
        fields = {"name": f.name, "language": f.language, "category": f.category,
                  "body_preview": f.body_preview, "variable_count": f.variable_count,
                  "approval_status": f.approval_status, "is_active": True}
        row = existing.get(f.content_sid)
        if row is None:
            template_repo.create(content_sid=f.content_sid, created_by=user.employee_id,
                                 updated_by=user.employee_id, **fields)
            continue
        changed = {k: v for k, v in fields.items() if getattr(row, k) != v}
        if changed:
            template_repo.update(row.id, updated_by=user.employee_id, **changed)
    fetched_sids = {f.content_sid for f in fetched}
    for sid, row in existing.items():
        if sid not in fetched_sids and row.is_active:
            template_repo.update(row.id, is_active=False, updated_by=user.employee_id)

    rows = sorted(template_repo.list(), key=lambda t: t.name.lower())
    return [activity_models.WhatsAppTemplateOut.model_validate(r) for r in rows]


@handle_errors("process inbound whatsapp")
def process_inbound_whatsapp(
    lead_repo: LeadRepository, comm_repo: CommunicationRepository, *,
    from_number: str, body: str, message_sid: str,
) -> activity_models.WhatsAppIntakeResult:
    """The WhatsApp half of message intake, called once per Twilio webhook
    hit (one call = one inbound message) — mirrors
    crm_service.process_inbound_sms() exactly. `from_number` arrives
    already stripped of Twilio's "whatsapp:" prefix (see
    server/crm_routes.py's route handler) — that prefix must never reach
    Lead.whatsapp_number or Communication.from_address.

    An unmatched sender does NOT get a new Lead auto-created (same
    reasoning as SMS: Lead.contact_email is required and an inbound
    WhatsApp message carries no email address to satisfy it) — matched_lead
    =False is the signal an AE/ADMIN needs to set that Lead's
    whatsapp_number by hand first.
    """
    if message_sid:
        existing = comm_repo.find_by_provider_message_id(message_sid)
        if existing is not None:
            return activity_models.WhatsAppIntakeResult(
                matched_lead=existing.lead_id is not None, lead_id=existing.lead_id,
                communication_id=existing.id, duplicate=True)

    lead = lead_repo.find_by_whatsapp_number(from_number)
    if lead is None:
        return activity_models.WhatsAppIntakeResult(matched_lead=False)

    row = comm_repo.create(
        lead_id=lead.id, account_id=None, agreement_id=None,
        direction="INBOUND", channel=LeadCommunicationChannel.WHATSAPP.value,
        body=body, from_address=from_number, provider_message_id=message_sid or None,
        occurred_at=_now(), source="WHATSAPP_INTAKE", logged_by_employee_id=None,
        created_by=_WHATSAPP_INTAKE_USER_ID, updated_by=_WHATSAPP_INTAKE_USER_ID,
    )
    # Refresh the 24-hour customer-service window on every real (non-
    # duplicate) inbound message — see Lead.whatsapp_window_expires_at.
    lead_repo.update(lead.id, whatsapp_window_expires_at=_now() + _WHATSAPP_WINDOW,
                     updated_by=_WHATSAPP_INTAKE_USER_ID)
    return activity_models.WhatsAppIntakeResult(matched_lead=True, lead_id=lead.id, communication_id=row.id)


@handle_errors("process whatsapp status callback")
def process_whatsapp_status_callback(
    comm_repo: CommunicationRepository, *,
    message_sid: str, message_status: str, error_code: str | None,
) -> None:
    """Twilio calls this once per delivery-status transition (queued -> sent
    -> delivered/read, or -> failed/undelivered) for a message this service
    itself sent via send_lead_whatsapp(). Looks the Communication row up by
    provider_message_id (same idempotency key inbound intake uses) and
    updates it in place — no Communication is ever created here.

    Silently no-ops (does not raise) if the SID isn't found or the status
    value isn't one of the known ones, rather than erroring — a status
    webhook must never fail loudly enough to make Twilio retry forever over
    something this service can't act on anyway.
    """
    if not message_sid:
        return
    existing = comm_repo.find_by_provider_message_id(message_sid)
    if existing is None:
        return
    status = (message_status or "").lower()
    if status not in _DELIVERY_STATUSES:
        return
    comm_repo.update(
        existing.id, delivery_status=status, failure_code=error_code or None,
        updated_by=_WHATSAPP_INTAKE_USER_ID,
    )
