"""Twilio Voice browser calling business logic — the Dial Pad built into a
Lead's existing "Log a call" modal. No separate call table: a Dial Pad call
is one row in the same `communication` table (channel="CALL"), same as a
manually-logged call — see models/activity_models.py.

Three entry points, one Communication record per real call throughout:
- mint_lead_call_token() — JWT-authenticated (mirrors send_lead_sms()'s
  shape): checks Lead access, mints a browser Access Token. No Communication
  row is created here — the call hasn't been placed yet.
- handle_voice_connect_webhook() — Twilio-authenticated: called the instant
  the browser's Voice SDK reaches TWILIO_VOICE_TWIML_APP_SID. This is where
  the ONE Communication row for this call is created (idempotent on the
  parent Call SID, in case Twilio ever retries this webhook), and where the
  TwiML telling Twilio who to actually dial is returned.
- process_voice_status_callback() — Twilio-authenticated: updates that SAME
  row's delivery_status/call_disposition_id/call_duration_seconds/
  failure_code as Twilio's callbacks arrive. Never creates a row.

Twilio's own parent/child call-leg split matters here: the Call SID the
browser sees (and the one this module keys everything off) is the PARENT
call (browser <-> Twilio). The actual PSTN leg to the Lead's phone is a
CHILD call Twilio creates from the <Dial><Number> in the connect webhook's
TwiML response, with its own SID — its status callbacks carry both `CallSid`
(the child's own) and `ParentCallSid` (matching what we stored), which is
why process_voice_status_callback() looks up by ParentCallSid first.
"""
from datetime import datetime, timezone
from uuid import UUID

from src.integrations import twilio_voice
from src.models import activity_models
from src.models.enums import LeadCommunicationChannel
from src.repositories._base import resolve_lookup_id
from src.repositories.activity_repository import CommunicationRepository, get_call_disposition_repository
from src.repositories.crm_repository import LeadRepository
from src.services.activity_service import _communication_out
from src.utils.error_handling import handle_errors
from src.utils.exceptions import DomainError
from src.utils.scope import require_lead_scope
from src.utils.security import CurrentUser

#: Stamped as created_by/updated_by on the Communication row the connect
#: webhook creates and the status callback updates — mirrors
#: whatsapp_service._WHATSAPP_INTAKE_USER_ID; there's no JWT-carrying
#: CurrentUser in a request Twilio itself makes, only the employee id
#: recovered from the browser Client's "client:<id>" From address (see
#: handle_voice_connect_webhook() below), which may not resolve to a real
#: logged_by_employee_id FK if that string isn't a real employee UUID.
_VOICE_WEBHOOK_FALLBACK_USER_ID = "voice-webhook"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_lead_or_404(lead_repo: LeadRepository, lid):
    row = lead_repo.get(lid)
    if row is None:
        raise DomainError("LEAD_NOT_FOUND", f"No lead '{lid}'.", 404)
    return row


@handle_errors("mint lead call token")
def mint_lead_call_token(user: CurrentUser, lead_repo: LeadRepository, lid) -> activity_models.VoiceAccessTokenOut:
    """Checked here, once, at token-mint time — exactly where
    activity_service.send_lead_sms()/send_lead_whatsapp() check Lead access,
    since minting this token is the one JWT-authenticated step in the whole
    flow; everything downstream (the connect/status webhooks) is Twilio-
    authenticated instead, same trust boundary as every other inbound
    webhook in this codebase."""
    _get_lead_or_404(lead_repo, lid)
    require_lead_scope(user, lead_repo, lid, for_write=True)
    token = twilio_voice.mint_access_token(identity=user.employee_id)
    return activity_models.VoiceAccessTokenOut(token=token, identity=user.employee_id)


@handle_errors("handle voice connect webhook")
def handle_voice_connect_webhook(
    lead_repo: LeadRepository, comm_repo: CommunicationRepository, *,
    parent_call_sid: str, from_field: str, to_number: str, lead_id_raw: str,
) -> str:
    """Returns TwiML. `from_field` is Twilio's own `From` param for a
    browser-originated call, shaped "client:<employee_id>" — parsed back to
    an employee id purely for created_by/updated_by attribution, same
    reasoning as SMS/email intake's synthetic user ids."""
    existing = comm_repo.find_by_provider_message_id(parent_call_sid) if parent_call_sid else None
    if existing is None:
        actor = from_field.removeprefix("client:") if from_field else _VOICE_WEBHOOK_FALLBACK_USER_ID
        lead = None
        if lead_id_raw:
            try:
                lead = lead_repo.get(UUID(lead_id_raw))
            except ValueError:
                lead = None
        subject = _default_call_subject(lead) if lead is not None else None
        comm_repo.create(
            lead_id=lead.id if lead is not None else None, account_id=None, agreement_id=None,
            direction="OUTBOUND", channel=LeadCommunicationChannel.CALL.value,
            subject=subject, to_recipients=to_number, occurred_at=_now(),
            source="VOICE_DIAL_PAD", provider_message_id=parent_call_sid or None,
            delivery_status="initiated",
            created_by=actor, updated_by=actor,
        )
    caller_id = twilio_voice.get_voice_caller_id()
    public_base_url = twilio_voice.get_voice_public_base_url()
    status_callback_url = f"{public_base_url.rstrip('/')}/api/v1/voice/webhook/status" if public_base_url else None
    return twilio_voice.build_connect_twiml(
        to_number=to_number, caller_id=caller_id or "", status_callback_url=status_callback_url)


def _default_call_subject(lead) -> str:
    name = " ".join(part for part in (lead.first_name, lead.last_name) if part).strip()
    return f"Call with {name}".strip() or "Call"


@handle_errors("process voice status callback")
def process_voice_status_callback(
    comm_repo: CommunicationRepository, *,
    call_sid: str, parent_call_sid: str | None, call_status: str,
    call_duration: str | None, error_code: str | None,
) -> None:
    """Looks up the Communication row by ParentCallSid first (the child PSTN
    leg's own status callback, which is where CallStatus/CallDuration
    actually come from — see this module's docstring), falling back to
    CallSid for the rare case this fires for the parent leg itself. Silently
    no-ops if no match — a status webhook must never fail loudly enough to
    make Twilio retry forever over a call this service isn't tracking."""
    lookup_sid = parent_call_sid or call_sid
    if not lookup_sid:
        return
    existing = comm_repo.find_by_provider_message_id(lookup_sid)
    if existing is None:
        return

    status = (call_status or "").lower()
    changes: dict = {"delivery_status": status, "updated_by": _VOICE_WEBHOOK_FALLBACK_USER_ID}

    if status in twilio_voice.TERMINAL_CALL_STATUSES:
        disposition_code = twilio_voice.map_call_status_to_disposition_code(status)
        if disposition_code is not None:
            changes["call_disposition_id"] = resolve_lookup_id(
                get_call_disposition_repository(), disposition_code,
                "CALL_DISPOSITION_INVALID", "call disposition")
        if call_duration:
            try:
                changes["call_duration_seconds"] = int(call_duration)
            except ValueError:
                pass
        if error_code:
            changes["failure_code"] = error_code

    comm_repo.update(existing.id, **changes)


@handle_errors("update call notes")
def update_call_notes(
    user: CurrentUser, lead_repo: LeadRepository, comm_repo: CommunicationRepository,
    lid, comm_id, payload: activity_models.UpdateCallNotesRequest,
) -> activity_models.CommunicationOut:
    """The one thing a rep may still edit on a Dial-Pad-created CALL row
    once Outcome/Duration are Twilio-driven — mirrors
    activity_service.mark_communication_opened()'s shape (fetch + scope +
    channel check + narrow comm_repo.update()), not a general Communication
    PATCH: every other channel/field stays append-only, unchanged."""
    _get_lead_or_404(lead_repo, lid)
    require_lead_scope(user, lead_repo, lid, for_write=True)
    row = comm_repo.get(comm_id)
    if row is None or row.lead_id != lid:
        raise DomainError("COMMUNICATION_NOT_FOUND", f"No communication '{comm_id}' on lead '{lid}'.", 404)
    if row.channel != LeadCommunicationChannel.CALL.value:
        raise DomainError("NOT_A_CALL", "Only a CALL communication's subject/notes can be edited this way.", 422)

    changes = payload.model_dump(exclude_unset=True)
    changes["updated_by"] = user.employee_id
    updated = comm_repo.update(comm_id, **changes)
    return _communication_out(updated)
