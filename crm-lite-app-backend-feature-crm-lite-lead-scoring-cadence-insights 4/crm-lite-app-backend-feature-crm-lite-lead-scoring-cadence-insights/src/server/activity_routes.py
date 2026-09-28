"""Activity module routes (§1/§11 of the API spec) — 7 endpoints: account &
agreement communications, notifications, audit log.

IMPLEMENTED — see services/activity_service.py. Notifications are
system-generated only (no public create endpoint); audit rows are written
server-side by repositories._base's generic CRUD hook, not via a public POST.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from src.models import activity_models
from src.repositories.activity_repository import (
    get_audit_log_repository,
    get_call_disposition_repository,
    get_communication_repository,
    get_notification_repository,
    get_whatsapp_template_repository,
)
from src.repositories.contracts_repository import get_agreement_repository
from src.repositories.crm_repository import get_account_repository, get_lead_repository
from src.integrations.twilio_whatsapp import get_whatsapp_sender, get_whatsapp_template_source
from src.services import activity_service, voice_service, whatsapp_service
from src.services.email_client import get_email_sender
from src.services.sms_service import get_sms_sender
from src.utils.permissions import requires
from src.utils.security import CurrentUser

router = APIRouter(tags=["Activity"])


# ---- Account communications ----
@router.get("/accounts/{account_id}/communications",
           response_model=list[activity_models.CommunicationOut])
def list_account_communications(account_id: str, u: CurrentUser = Depends(requires("platform.read")),
                                 account_repo=Depends(get_account_repository),
                                 comm_repo=Depends(get_communication_repository)):
    return activity_service.list_account_communications(u, account_repo, comm_repo, account_id)


@router.post("/accounts/{account_id}/communications", status_code=201,
            response_model=activity_models.CommunicationOut)
def add_account_communication(account_id: str, payload: activity_models.CommunicationCreate,
                               u: CurrentUser = Depends(requires("accounts.write")),
                               account_repo=Depends(get_account_repository),
                               comm_repo=Depends(get_communication_repository),
                               disposition_repo=Depends(get_call_disposition_repository)):
    return activity_service.add_account_communication(
        u, account_repo, comm_repo, disposition_repo, account_id, payload)


# ---- Agreement communications ----
@router.get("/agreements/{agreement_id}/communications",
           response_model=list[activity_models.CommunicationOut])
def list_agreement_communications(agreement_id: str, u: CurrentUser = Depends(requires("platform.read")),
                                  account_repo=Depends(get_account_repository),
                                  agreement_repo=Depends(get_agreement_repository),
                                  comm_repo=Depends(get_communication_repository)):
    return activity_service.list_agreement_communications(u, account_repo, agreement_repo,
                                                          comm_repo, agreement_id)


@router.post("/agreements/{agreement_id}/communications", status_code=201,
            response_model=activity_models.CommunicationOut)
def add_agreement_communication(agreement_id: str, payload: activity_models.CommunicationCreate,
                                u: CurrentUser = Depends(requires("accounts.write")),
                                account_repo=Depends(get_account_repository),
                                agreement_repo=Depends(get_agreement_repository),
                                comm_repo=Depends(get_communication_repository),
                                disposition_repo=Depends(get_call_disposition_repository)):
    return activity_service.add_agreement_communication(u, account_repo, agreement_repo, comm_repo,
                                                        disposition_repo, agreement_id, payload)


# ---- Lead communications / Email & Call Insights ----
@router.get("/leads/{lead_id}/communications", response_model=list[activity_models.CommunicationOut])
def list_lead_communications(lead_id: UUID, u: CurrentUser = Depends(requires("platform.read")),
                             lead_repo=Depends(get_lead_repository),
                             comm_repo=Depends(get_communication_repository)):
    return activity_service.list_lead_communications(u, lead_repo, comm_repo, lead_id)


@router.post("/leads/{lead_id}/communications", status_code=201,
            response_model=activity_models.CommunicationOut)
def add_lead_communication(lead_id: UUID, payload: activity_models.CommunicationCreate,
                           u: CurrentUser = Depends(requires("leads.write")),
                           lead_repo=Depends(get_lead_repository),
                           comm_repo=Depends(get_communication_repository),
                           disposition_repo=Depends(get_call_disposition_repository)):
    return activity_service.add_lead_communication(u, lead_repo, comm_repo, disposition_repo, lead_id, payload)


@router.post("/leads/{lead_id}/communications/{comm_id}/opened", response_model=activity_models.CommunicationOut)
def mark_communication_opened(lead_id: UUID, comm_id: UUID,
                              payload: activity_models.CommunicationTrackEvent = activity_models.CommunicationTrackEvent(),
                              u: CurrentUser = Depends(requires("leads.write")),
                              lead_repo=Depends(get_lead_repository),
                              comm_repo=Depends(get_communication_repository)):
    return activity_service.mark_communication_opened(u, lead_repo, comm_repo, lead_id, comm_id, payload)


@router.post("/leads/{lead_id}/communications/{comm_id}/replied", response_model=activity_models.CommunicationOut)
def mark_communication_replied(lead_id: UUID, comm_id: UUID,
                               payload: activity_models.CommunicationTrackEvent = activity_models.CommunicationTrackEvent(),
                               u: CurrentUser = Depends(requires("leads.write")),
                               lead_repo=Depends(get_lead_repository),
                               comm_repo=Depends(get_communication_repository)):
    return activity_service.mark_communication_replied(u, lead_repo, comm_repo, lead_id, comm_id, payload)


@router.post("/leads/{lead_id}/communications/send", status_code=201,
            response_model=activity_models.CommunicationOut)
def send_lead_email(lead_id: UUID, payload: activity_models.SendEmailRequest,
                    u: CurrentUser = Depends(requires("leads.write")),
                    lead_repo=Depends(get_lead_repository),
                    comm_repo=Depends(get_communication_repository),
                    disposition_repo=Depends(get_call_disposition_repository),
                    email_sender=Depends(get_email_sender)):
    return activity_service.send_lead_email(
        u, lead_repo, comm_repo, disposition_repo, email_sender, lead_id, payload)


@router.post("/leads/{lead_id}/sms", status_code=201,
            response_model=activity_models.CommunicationOut)
def send_lead_sms(lead_id: UUID, payload: activity_models.SendSmsRequest,
                  u: CurrentUser = Depends(requires("leads.write")),
                  lead_repo=Depends(get_lead_repository),
                  comm_repo=Depends(get_communication_repository),
                  disposition_repo=Depends(get_call_disposition_repository),
                  sms_sender=Depends(get_sms_sender)):
    return activity_service.send_lead_sms(
        u, lead_repo, comm_repo, disposition_repo, sms_sender, lead_id, payload)


@router.post("/leads/{lead_id}/whatsapp", status_code=201,
            response_model=activity_models.CommunicationOut)
def send_lead_whatsapp(lead_id: UUID, payload: activity_models.SendWhatsAppRequest,
                       u: CurrentUser = Depends(requires("leads.write")),
                       lead_repo=Depends(get_lead_repository),
                       comm_repo=Depends(get_communication_repository),
                       template_repo=Depends(get_whatsapp_template_repository),
                       whatsapp_sender=Depends(get_whatsapp_sender)):
    return whatsapp_service.send_lead_whatsapp(
        u, lead_repo, comm_repo, template_repo, whatsapp_sender, lead_id, payload)


@router.get("/whatsapp/templates", response_model=list[activity_models.WhatsAppTemplateOut])
def list_whatsapp_templates(u: CurrentUser = Depends(requires("leads.write")),
                            template_repo=Depends(get_whatsapp_template_repository)):
    return whatsapp_service.list_whatsapp_templates(template_repo)


@router.post("/whatsapp/templates/sync", response_model=list[activity_models.WhatsAppTemplateOut])
def sync_whatsapp_templates(u: CurrentUser = Depends(requires("admin")),
                            template_repo=Depends(get_whatsapp_template_repository),
                            source=Depends(get_whatsapp_template_source)):
    return whatsapp_service.sync_whatsapp_templates(u, template_repo, source)


# ---- Dial Pad browser calling (Twilio Voice) ----
@router.get("/leads/{lead_id}/voice-token", response_model=activity_models.VoiceAccessTokenOut)
def get_lead_voice_token(lead_id: UUID, u: CurrentUser = Depends(requires("leads.write")),
                         lead_repo=Depends(get_lead_repository)):
    return voice_service.mint_lead_call_token(u, lead_repo, lead_id)


@router.post("/leads/{lead_id}/communications/{comm_id}/call-notes",
            response_model=activity_models.CommunicationOut)
def update_call_notes(lead_id: UUID, comm_id: UUID, payload: activity_models.UpdateCallNotesRequest,
                      u: CurrentUser = Depends(requires("leads.write")),
                      lead_repo=Depends(get_lead_repository),
                      comm_repo=Depends(get_communication_repository)):
    return voice_service.update_call_notes(u, lead_repo, comm_repo, lead_id, comm_id, payload)


@router.get("/leads/{lead_id}/email-insights", response_model=activity_models.LeadEmailInsightsOut)
def get_lead_email_insights(lead_id: UUID, u: CurrentUser = Depends(requires("platform.read")),
                            lead_repo=Depends(get_lead_repository),
                            comm_repo=Depends(get_communication_repository)):
    return activity_service.get_lead_email_insights(u, lead_repo, comm_repo, lead_id)


@router.get("/leads/{lead_id}/call-insights", response_model=activity_models.LeadCallInsightsOut)
def get_lead_call_insights(lead_id: UUID, u: CurrentUser = Depends(requires("platform.read")),
                           lead_repo=Depends(get_lead_repository),
                           comm_repo=Depends(get_communication_repository)):
    return activity_service.get_lead_call_insights(u, lead_repo, comm_repo, lead_id)


# ---- Notifications ----
@router.get("/notifications", response_model=list[activity_models.NotificationOut])
def list_notifications(unacknowledged_only: bool = Query(default=False),
                       u: CurrentUser = Depends(requires("platform.read")),
                       notification_repo=Depends(get_notification_repository)):
    return activity_service.list_notifications(u, notification_repo, unacknowledged_only)


@router.patch("/notifications/{notification_id}/acknowledge",
             response_model=activity_models.NotificationOut)
def acknowledge_notification(notification_id: UUID, u: CurrentUser = Depends(requires("platform.read")),
                             notification_repo=Depends(get_notification_repository)):
    return activity_service.acknowledge_notification(u, notification_repo, notification_id)


# ---- Audit ----
@router.get("/audit", response_model=list[activity_models.AuditLogOut])
def list_audit(entity_type: str | None = Query(default=None), entity_id: str | None = Query(default=None),
              u: CurrentUser = Depends(requires("audit.read")),
              audit_repo=Depends(get_audit_log_repository)):
    return activity_service.list_audit(u, audit_repo, entity_type=entity_type, entity_id=entity_id)
