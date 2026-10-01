"""Activity module business logic (§1/§11 of the API spec) — Communications,
Notifications, Audit log. IMPLEMENTED.

Rules enforced:
- communications : append-only (no update/delete endpoints exist); direction
                   must be INBOUND or OUTBOUND; account/agreement must exist.
- notifications  : system-generated only (never created via a public POST —
                   see §13's scheduled jobs, not part of this API surface);
                   the only mutation exposed here is acknowledge.
- audit          : rows are written server-side by repositories._base's
                   generic CRUD hook on every create/update/delete across
                   every module, not via a public POST; read access is
                   scoped per §4's capability matrix — SALES has none,
                   ACCOUNT_EXEC sees only rows they performed, LEADERSHIP/
                   ADMIN see all.

Depends only on repository classes — never on a SQLAlchemy Session directly.
"""
from datetime import datetime, timezone

from src.config.config_reader import get_settings
from src.models import activity_models
from src.models.enums import CallOutcome, LeadCommunicationChannel, LeadStatus
from src.repositories._base import resolve_lookup_id
from src.repositories.activity_repository import (
    AuditLogRepository,
    CallDispositionRepository,
    CommunicationRepository,
    NotificationRepository,
    get_call_disposition_repository,
)
from src.repositories.contracts_repository import AgreementRepository
from src.repositories.crm_repository import AccountRepository, LeadRepository
from src.services.admin_service import verified_employee_uuid
from src.services.email_client import EmailSender
from src.services.sms_service import SmsSender
from src.utils.error_handling import handle_errors
from src.utils.exceptions import DomainError
from src.utils.phone import normalize_phone
from src.utils.scope import require_account_scope, require_lead_scope
from src.utils.security import CurrentUser

_DIRECTIONS = {"INBOUND", "OUTBOUND"}
_LEAD_COMM_CHANNELS = {c.value for c in LeadCommunicationChannel}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _call_disposition_code_map() -> dict[int, str]:
    """{call_disposition.id: code} — call_disposition is admin-managed but
    tiny, so resolving it once per call site (like crm_service's
    _account_type_map()) avoids an N+1 without needing to cache across
    requests (an admin editing it should take effect immediately)."""
    return {d.id: d.code for d in get_call_disposition_repository().list()}


def _communication_out(row, disposition_map: dict[int, str] | None = None) -> activity_models.CommunicationOut:
    codes = disposition_map if disposition_map is not None else _call_disposition_code_map()
    return activity_models.CommunicationOut(
        id=row.id, account_id=row.account_id, agreement_id=row.agreement_id, lead_id=row.lead_id,
        received_via_team_id=row.received_via_team_id, direction=row.direction,
        channel=row.channel, subject=row.subject, body=row.body, notes=row.notes,
        from_address=row.from_address,
        to_recipients=row.to_recipients, cc_recipients=row.cc_recipients,
        graph_message_id=row.graph_message_id, provider_message_id=row.provider_message_id,
        occurred_at=row.occurred_at, source=row.source,
        call_duration_seconds=row.call_duration_seconds,
        call_outcome=codes.get(row.call_disposition_id) if row.call_disposition_id else None,
        opened_at=row.opened_at, replied_at=row.replied_at,
        delivery_status=row.delivery_status, failure_code=row.failure_code,
        whatsapp_template_id=row.whatsapp_template_id, template_variables=row.template_variables,
        media_url=row.media_url, media_content_type=row.media_content_type,
        logged_by_employee_id=row.logged_by_employee_id,
        created_at=row.created_at, updated_at=row.updated_at,
        created_by=row.created_by, updated_by=row.updated_by,
    )


def _create_communication(user: CurrentUser, comm_repo: CommunicationRepository,
                          disposition_repo: CallDispositionRepository,
                          payload: activity_models.CommunicationCreate,
                          *, account_id: str | None, agreement_id: str | None, lead_id=None,
                          ) -> activity_models.CommunicationOut:
    direction = payload.direction.upper()
    if direction not in _DIRECTIONS:
        raise DomainError("INVALID_DIRECTION", "direction must be INBOUND or OUTBOUND.", 422)
    call_disposition_id = None
    if payload.call_outcome is not None:
        call_disposition_id = resolve_lookup_id(
            disposition_repo, payload.call_outcome, "CALL_OUTCOME_INVALID", "call disposition")
    row = comm_repo.create(
        account_id=account_id, agreement_id=agreement_id, lead_id=lead_id,
        received_via_team_id=payload.received_via_team_id, direction=direction,
        channel=payload.channel, subject=payload.subject, body=payload.body, notes=payload.notes,
        from_address=payload.from_address,
        to_recipients=payload.to_recipients, cc_recipients=payload.cc_recipients,
        graph_message_id=payload.graph_message_id, provider_message_id=payload.provider_message_id,
        occurred_at=payload.occurred_at,
        source=payload.source or "API",
        call_duration_seconds=payload.call_duration_seconds, call_disposition_id=call_disposition_id,
        logged_by_employee_id=verified_employee_uuid(user),
        created_by=user.employee_id, updated_by=user.employee_id,
    )
    return _communication_out(row)


# --- Account communications -----------------------------------------------
@handle_errors("list account communications")
def list_account_communications(user: CurrentUser, account_repo: AccountRepository,
                                 comm_repo: CommunicationRepository,
                                 cid: str) -> list[activity_models.CommunicationOut]:
    if account_repo.get(cid) is None:
        raise DomainError("ACCOUNT_NOT_FOUND", f"No account '{cid}'.", 404)
    require_account_scope(user, account_repo, cid, "Account is outside your data scope.")
    disposition_map = _call_disposition_code_map()
    rows = sorted(comm_repo.list_for_account(cid), key=lambda r: r.occurred_at, reverse=True)
    return [_communication_out(r, disposition_map) for r in rows]


@handle_errors("add account communication")
def add_account_communication(user: CurrentUser, account_repo: AccountRepository,
                               comm_repo: CommunicationRepository, disposition_repo: CallDispositionRepository,
                               cid: str, payload: activity_models.CommunicationCreate,
                               ) -> activity_models.CommunicationOut:
    if account_repo.get(cid) is None:
        raise DomainError("ACCOUNT_NOT_FOUND", f"No account '{cid}'.", 404)
    require_account_scope(user, account_repo, cid, "Account is outside your data scope.", for_write=True)
    return _create_communication(user, comm_repo, disposition_repo, payload, account_id=cid, agreement_id=None)


# --- Agreement communications -----------------------------------------------
@handle_errors("list agreement communications")
def list_agreement_communications(user: CurrentUser, account_repo: AccountRepository,
                                  agreement_repo: AgreementRepository, comm_repo: CommunicationRepository,
                                  aid: str) -> list[activity_models.CommunicationOut]:
    agreement = agreement_repo.get(aid)
    if agreement is None:
        raise DomainError("AGREEMENT_NOT_FOUND", f"No agreement '{aid}'.", 404)
    require_account_scope(user, account_repo, agreement.account_id, "Agreement is outside your data scope.")
    disposition_map = _call_disposition_code_map()
    rows = sorted(comm_repo.list_for_agreement(aid), key=lambda r: r.occurred_at, reverse=True)
    return [_communication_out(r, disposition_map) for r in rows]


@handle_errors("add agreement communication")
def add_agreement_communication(user: CurrentUser, account_repo: AccountRepository,
                                agreement_repo: AgreementRepository, comm_repo: CommunicationRepository,
                                disposition_repo: CallDispositionRepository,
                                aid: str, payload: activity_models.CommunicationCreate,
                                ) -> activity_models.CommunicationOut:
    agreement = agreement_repo.get(aid)
    if agreement is None:
        raise DomainError("AGREEMENT_NOT_FOUND", f"No agreement '{aid}'.", 404)
    require_account_scope(user, account_repo, agreement.account_id, "Agreement is outside your data scope.",
                          for_write=True)
    return _create_communication(user, comm_repo, disposition_repo, payload, account_id=None, agreement_id=aid)


# --- Lead communications / Email & Call Insights -------------------------------
# Lead-level Communication rows are the shared source of truth for both the
# raw activity log and the aggregate insights below — and are also what
# crm_service.complete_cadence_task() auto-logs when a CALL/EMAIL cadence
# step is completed, so a rep's cadence work shows up here without a second
# manual log entry.


def _get_lead_or_404(lead_repo: LeadRepository, lid):
    row = lead_repo.get(lid)
    if row is None:
        raise DomainError("LEAD_NOT_FOUND", f"No lead '{lid}'.", 404)
    return row


#: Statuses a lead's first successful contact may move forward to CONTACTED.
#: A lead the rep already moved past these (or into a terminal state) by hand
#: keeps its status — first contact only ever records contacted=True then,
#: never drags the status backwards.
_FIRST_CONTACT_ADVANCES_FROM = {LeadStatus.NEW.value, LeadStatus.ATTEMPTING_CONTACT.value}

#: Logged-call outcomes that mean the rep actually reached the lead — a
#: NO_ANSWER/BUSY/VOICEMAIL/WRONG_NUMBER call is an attempt, not a contact.
_CONTACT_MADE_CALL_OUTCOMES = {CallOutcome.CONNECTED.value}


def mark_lead_as_contacted_if_first_contact(lead_repo: LeadRepository, lid, *, updated_by: str):
    """Call ONLY after an Email/SMS/Call has succeeded. The one automatic
    status transition tied to outreach: contacted False -> True (and status
    -> CONTACTED if still in _FIRST_CONTACT_ADVANCES_FROM), exactly once.
    Once contacted is True this is a no-op, so later activities never touch
    whatever status the rep has since set.

    Race-free via update_if()'s row lock: two activities finishing at the
    same time both read contacted=False, but only the first to take the lock
    still matches `expected`; the second gets None, re-reads, sees
    contacted=True and stops. The retry also covers a manual status change
    landing between the read and the lock."""
    for _ in range(3):
        lead = lead_repo.get(lid)
        if lead is None or lead.contacted:
            return lead
        fields: dict = {"contacted": True, "updated_by": updated_by}
        if lead.status in _FIRST_CONTACT_ADVANCES_FROM:
            fields["status"] = LeadStatus.CONTACTED.value
        updated = lead_repo.update_if(lid, expected={"contacted": False, "status": lead.status}, **fields)
        if updated is not None:
            return updated
    return lead_repo.get(lid)


@handle_errors("list lead communications")
def list_lead_communications(user: CurrentUser, lead_repo: LeadRepository,
                             comm_repo: CommunicationRepository,
                             lid) -> list[activity_models.CommunicationOut]:
    _get_lead_or_404(lead_repo, lid)
    require_lead_scope(user, lead_repo, lid)
    disposition_map = _call_disposition_code_map()
    rows = sorted(comm_repo.list_for_lead(lid), key=lambda r: r.occurred_at, reverse=True)
    return [_communication_out(r, disposition_map) for r in rows]


@handle_errors("add lead communication")
def add_lead_communication(user: CurrentUser, lead_repo: LeadRepository,
                           comm_repo: CommunicationRepository, disposition_repo: CallDispositionRepository,
                           lid, payload: activity_models.CommunicationCreate,
                           ) -> activity_models.CommunicationOut:
    _get_lead_or_404(lead_repo, lid)
    require_lead_scope(user, lead_repo, lid, for_write=True)
    channel = payload.channel.upper()
    if channel not in _LEAD_COMM_CHANNELS:
        raise DomainError(
            "LEAD_COMMUNICATION_CHANNEL_INVALID",
            f"'{payload.channel}' is not a valid channel for a lead activity. Choose from: "
            f"{', '.join(sorted(_LEAD_COMM_CHANNELS))}.", 422)
    payload = payload.model_copy(update={"channel": channel})
    created = _create_communication(
        user, comm_repo, disposition_repo, payload, account_id=None, agreement_id=None, lead_id=lid)
    # "Log a call" — only a call that actually reached the lead counts.
    if channel == LeadCommunicationChannel.CALL.value and created.call_outcome in _CONTACT_MADE_CALL_OUTCOMES:
        mark_lead_as_contacted_if_first_contact(lead_repo, lid, updated_by=user.employee_id)
    return created


@handle_errors("send lead email")
def send_lead_email(user: CurrentUser, lead_repo: LeadRepository, comm_repo: CommunicationRepository,
                    disposition_repo: CallDispositionRepository, email_sender: EmailSender, lid,
                    payload: activity_models.SendEmailRequest) -> activity_models.CommunicationOut:
    """The "click send" half of AI-assisted drafting (AI-3/AT-1): actually
    delivers the email via email_sender, then logs it as a Communication on
    success — mirroring how crm_service.complete_cadence_task() auto-logs a
    cadence-driven email, so this shows up in Email Insights the same way."""
    lead = _get_lead_or_404(lead_repo, lid)
    require_lead_scope(user, lead_repo, lid, for_write=True)
    to_address = payload.to_address or lead.contact_email
    if not to_address:
        raise DomainError(
            "EMAIL_RECIPIENT_MISSING",
            "This lead has no contact_email on file — pass to_address explicitly.", 422)

    email_sender.send(to_address, payload.subject, payload.body)

    create_payload = activity_models.CommunicationCreate(
        direction="OUTBOUND", channel=LeadCommunicationChannel.EMAIL.value, subject=payload.subject,
        body=payload.body, from_address=get_settings().SMTP_FROM_ADDRESS,
        to_recipients=to_address, occurred_at=_now(), source="SENT",
    )
    created = _create_communication(
        user, comm_repo, disposition_repo, create_payload, account_id=None, agreement_id=None, lead_id=lid)
    mark_lead_as_contacted_if_first_contact(lead_repo, lid, updated_by=user.employee_id)
    return created


@handle_errors("send lead sms")
def send_lead_sms(user: CurrentUser, lead_repo: LeadRepository, comm_repo: CommunicationRepository,
                  disposition_repo: CallDispositionRepository, sms_sender: SmsSender, lid,
                  payload: activity_models.SendSmsRequest) -> activity_models.CommunicationOut:
    """The SMS action on a Lead's Cadence Activity tab: delivers via
    sms_sender, then logs it as a Communication on success — mirroring
    send_lead_email() above, just with Twilio in place of SMTP and the
    lead's phone (contact_phone, falling back to mobile_phone — same
    fallback order the "Log a call" flow already uses) in place of its
    contact_email."""
    lead = _get_lead_or_404(lead_repo, lid)
    require_lead_scope(user, lead_repo, lid, for_write=True)
    # Normalized here too, not just on Lead save, so leads stored before
    # that cleanup existed ("+91 7330671971") still send correctly.
    to_number = normalize_phone(lead.contact_phone) or normalize_phone(lead.mobile_phone)
    if not to_number:
        raise DomainError(
            "SMS_RECIPIENT_MISSING",
            "This lead has no contact_phone or mobile_phone on file.", 422)

    provider_message_id = sms_sender.send(to_number, payload.message)

    create_payload = activity_models.CommunicationCreate(
        direction="OUTBOUND", channel=LeadCommunicationChannel.SMS.value, body=payload.message,
        to_recipients=to_number, occurred_at=_now(), source="SENT",
        provider_message_id=provider_message_id,
    )
    created = _create_communication(
        user, comm_repo, disposition_repo, create_payload, account_id=None, agreement_id=None, lead_id=lid)
    mark_lead_as_contacted_if_first_contact(lead_repo, lid, updated_by=user.employee_id)
    return created


def _get_lead_communication_or_404(comm_repo: CommunicationRepository, lid, comm_id):
    row = comm_repo.get(comm_id)
    if row is None or row.lead_id != lid:
        raise DomainError("COMMUNICATION_NOT_FOUND", f"No communication '{comm_id}' on lead '{lid}'.", 404)
    return row


@handle_errors("mark communication opened")
def mark_communication_opened(user: CurrentUser, lead_repo: LeadRepository,
                              comm_repo: CommunicationRepository, lid, comm_id,
                              payload: activity_models.CommunicationTrackEvent,
                              ) -> activity_models.CommunicationOut:
    _get_lead_or_404(lead_repo, lid)
    require_lead_scope(user, lead_repo, lid, for_write=True)
    row = _get_lead_communication_or_404(comm_repo, lid, comm_id)
    if row.channel != LeadCommunicationChannel.EMAIL.value:
        raise DomainError("NOT_AN_EMAIL", "Only an EMAIL communication can be marked opened.", 422)
    if row.opened_at is None:  # first-open semantics — don't overwrite an earlier open
        row = comm_repo.update(comm_id, opened_at=payload.occurred_at or _now(), updated_by=user.employee_id)
    return _communication_out(row)


@handle_errors("mark communication replied")
def mark_communication_replied(user: CurrentUser, lead_repo: LeadRepository,
                               comm_repo: CommunicationRepository, lid, comm_id,
                               payload: activity_models.CommunicationTrackEvent,
                               ) -> activity_models.CommunicationOut:
    _get_lead_or_404(lead_repo, lid)
    require_lead_scope(user, lead_repo, lid, for_write=True)
    row = _get_lead_communication_or_404(comm_repo, lid, comm_id)
    if row.channel != LeadCommunicationChannel.EMAIL.value:
        raise DomainError("NOT_AN_EMAIL", "Only an EMAIL communication can be marked replied.", 422)
    if row.replied_at is None:  # first-reply semantics — don't overwrite an earlier reply
        row = comm_repo.update(comm_id, replied_at=payload.occurred_at or _now(), updated_by=user.employee_id)
    return _communication_out(row)


@handle_errors("get lead email insights")
def get_lead_email_insights(user: CurrentUser, lead_repo: LeadRepository,
                            comm_repo: CommunicationRepository, lid,
                            ) -> activity_models.LeadEmailInsightsOut:
    _get_lead_or_404(lead_repo, lid)
    require_lead_scope(user, lead_repo, lid)
    emails = [c for c in comm_repo.list_for_lead(lid) if c.channel == LeadCommunicationChannel.EMAIL.value]
    outbound = [c for c in emails if c.direction == "OUTBOUND"]
    inbound_count = len(emails) - len(outbound)
    opened = sum(1 for c in outbound if c.opened_at is not None)
    replied = sum(1 for c in outbound if c.replied_at is not None)
    last_at = max((c.occurred_at for c in emails), default=None)
    return activity_models.LeadEmailInsightsOut(
        total_emails=len(emails), inbound_count=inbound_count, outbound_count=len(outbound),
        opened_count=opened, replied_count=replied,
        # Open/reply rates are only meaningful against emails we actually sent.
        open_rate_percent=round(opened / len(outbound) * 100, 1) if outbound else None,
        reply_rate_percent=round(replied / len(outbound) * 100, 1) if outbound else None,
        last_email_at=last_at,
    )


@handle_errors("get lead call insights")
def get_lead_call_insights(user: CurrentUser, lead_repo: LeadRepository,
                           comm_repo: CommunicationRepository, lid,
                           ) -> activity_models.LeadCallInsightsOut:
    _get_lead_or_404(lead_repo, lid)
    require_lead_scope(user, lead_repo, lid)
    disposition_map = _call_disposition_code_map()
    calls = [c for c in comm_repo.list_for_lead(lid) if c.channel == LeadCommunicationChannel.CALL.value]
    outcomes = [disposition_map.get(c.call_disposition_id) for c in calls if c.call_disposition_id]
    connected = sum(1 for o in outcomes if o == CallOutcome.CONNECTED.value)
    durations = [c.call_duration_seconds for c in calls if c.call_duration_seconds is not None]
    outcome_breakdown: dict[str, int] = {}
    for o in outcomes:
        outcome_breakdown[o] = outcome_breakdown.get(o, 0) + 1
    return activity_models.LeadCallInsightsOut(
        total_calls=len(calls), connected_count=connected,
        connected_rate_percent=round(connected / len(calls) * 100, 1) if calls else None,
        avg_duration_seconds=round(sum(durations) / len(durations), 1) if durations else None,
        last_call_at=max((c.occurred_at for c in calls), default=None),
        outcome_breakdown=outcome_breakdown,
    )


# --- Notifications -------------------------------------------------------------
def _notification_out(row) -> activity_models.NotificationOut:
    return activity_models.NotificationOut(
        id=row.id, agreement_id=row.agreement_id, account_id=row.account_id, lead_id=row.lead_id,
        recipient_employee_id=row.recipient_employee_id,
        notification_type=row.notification_type, severity=row.severity, message=row.message,
        sent_at=row.sent_at, acknowledged=row.acknowledged,
        created_at=row.created_at, updated_at=row.updated_at,
        created_by=row.created_by, updated_by=row.updated_by,
    )


@handle_errors("list notifications")
def list_notifications(user: CurrentUser, notification_repo: NotificationRepository,
                       unacknowledged_only: bool = False) -> list[activity_models.NotificationOut]:
    rows = notification_repo.list_unacknowledged() if unacknowledged_only else notification_repo.list()
    own = user.employee_uuid()
    rows = [r for r in rows if r.recipient_employee_id is None or r.recipient_employee_id == own]
    rows.sort(key=lambda r: r.sent_at, reverse=True)
    return [_notification_out(r) for r in rows]


@handle_errors("acknowledge notification")
def acknowledge_notification(user: CurrentUser, notification_repo: NotificationRepository,
                             notification_id) -> activity_models.NotificationOut:
    row = notification_repo.get(notification_id)
    if row is None:
        raise DomainError("NOTIFICATION_NOT_FOUND", f"No notification '{notification_id}'.", 404)
    updated = notification_repo.update(notification_id, acknowledged=True, updated_by=user.employee_id)
    return _notification_out(updated)


# --- Audit -----------------------------------------------------------------------
@handle_errors("list the audit log")
def list_audit(user: CurrentUser, audit_repo: AuditLogRepository, *,
               entity_type: str | None = None, entity_id: str | None = None,
               ) -> list[activity_models.AuditLogOut]:
    filters = {}
    if entity_type:
        filters["entity_type"] = entity_type
    if entity_id:
        filters["entity_id"] = entity_id
    rows = audit_repo.list(**filters)
    if not user.has_capability("audit.see_all"):
        own = user.employee_uuid()
        rows = [r for r in rows if own is not None and r.performed_by_employee_id == own]
    rows.sort(key=lambda r: r.performed_at, reverse=True)
    return [activity_models.AuditLogOut.model_validate(r) for r in rows]
