"""CRM module routes (§1/§6 of the API spec) — 21 endpoints: Accounts,
Contacts, Account assignments, Opportunities, Opportunity documents.

IMPLEMENTED — see services/crm_service.py.
"""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from src.models import activity_models, crm_models
from src.models.common import Page
from src.repositories.activity_repository import get_communication_repository, get_notification_repository
from src.repositories.admin_repository import get_employee_repository
from src.repositories.contracts_repository import get_agreement_repository
from src.repositories.crm_repository import (
    get_cadence_step_repository,
    get_cadence_task_repository,
    get_cadence_template_repository,
    get_campaign_repository,
    get_contact_repository,
    get_account_assignment_repository,
    get_account_repository,
    get_field_permission_repository,
    get_lead_cadence_enrollment_repository,
    get_lead_repository,
    get_lead_scoring_rule_repository,
    get_opportunity_document_repository,
    get_opportunity_repository,
    get_org_wide_default_repository,
    get_product_repository,
    get_record_share_repository,
    get_signal_repository,
)
from src.repositories.delivery_repository import get_asset_repository
from src.repositories.project_repository import get_project_repository
from src.services import crm_service, voice_service, whatsapp_service
from src.services.email_client import get_email_sender
from src.services.inbound_email_client import get_inbound_email_receiver
from src.services.llm_client import get_llm_client, get_optional_llm_client
from src.utils.permissions import requires
from src.utils.security import (
    CurrentUser,
    require_cadence_scheduler_secret,
    require_email_intake_secret,
    require_twilio_signature,
    require_twilio_voice_signature,
    require_twilio_whatsapp_signature,
)

router = APIRouter(tags=["CRM"])


# ---- Accounts ----
@router.get("/accounts", response_model=Page[crm_models.AccountOut])
def list_accounts(
    q: str | None = Query(default=None, description="Search on legal name"),
    account_type: str | None = Query(default=None, description="PROSPECT|CLIENT|VENDOR|PARTNER"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    u: CurrentUser = Depends(requires("accounts.read")),
    repo=Depends(get_account_repository),
):
    return crm_service.list_accounts(u, repo, q=q, account_type=account_type,
                                      page=page, page_size=page_size)


@router.post("/accounts", status_code=201, response_model=crm_models.AccountOut)
def create_account(payload: crm_models.AccountCreate,
                    u: CurrentUser = Depends(requires("accounts.create")),
                    repo=Depends(get_account_repository),
                    employees=Depends(get_employee_repository)):
    return crm_service.create_account(u, repo, employees, payload)


@router.get("/accounts/{account_id}", response_model=crm_models.AccountOut)
def get_account(account_id: str, u: CurrentUser = Depends(requires("accounts.read")),
                 repo=Depends(get_account_repository)):
    return crm_service.get_account(u, repo, account_id)


@router.patch("/accounts/{account_id}", response_model=crm_models.AccountOut)
def update_account(account_id: str, payload: crm_models.AccountUpdate,
                    u: CurrentUser = Depends(requires("accounts.edit")),
                    repo=Depends(get_account_repository),
                    employees=Depends(get_employee_repository)):
    return crm_service.update_account(u, repo, employees, account_id, payload)


@router.delete("/accounts/{account_id}", status_code=204)
def delete_account(account_id: str, u: CurrentUser = Depends(requires("accounts.delete")),
                    repo=Depends(get_account_repository),
                    agreements=Depends(get_agreement_repository),
                    projects=Depends(get_project_repository)):
    crm_service.delete_account(u, repo, agreements, projects, account_id)


@router.post("/accounts/{account_id}/promote", response_model=crm_models.AccountOut)
def promote_account(account_id: str,
                     u: CurrentUser = Depends(requires("accounts.promote")),
                     repo=Depends(get_account_repository),
                     agreements=Depends(get_agreement_repository)):
    return crm_service.promote_account(u, repo, agreements, account_id)


# ---- Contacts ----
@router.get("/accounts/{account_id}/contacts", response_model=list[crm_models.ContactOut])
def list_contacts(account_id: str, u: CurrentUser = Depends(requires("platform.read")),
                  account_repo=Depends(get_account_repository),
                  contact_repo=Depends(get_contact_repository)):
    return crm_service.list_contacts(u, account_repo, contact_repo, account_id)


@router.post("/accounts/{account_id}/contacts", status_code=201, response_model=crm_models.ContactOut)
def add_contact(account_id: str, payload: crm_models.ContactCreate,
                u: CurrentUser = Depends(requires("accounts.write")),
                account_repo=Depends(get_account_repository),
                contact_repo=Depends(get_contact_repository)):
    return crm_service.add_contact(u, account_repo, contact_repo, account_id, payload)


@router.patch("/contacts/{contact_id}", response_model=crm_models.ContactOut)
def update_contact(contact_id: UUID, payload: crm_models.ContactUpdate,
                   u: CurrentUser = Depends(requires("accounts.write")),
                   account_repo=Depends(get_account_repository),
                   contact_repo=Depends(get_contact_repository)):
    return crm_service.update_contact(u, account_repo, contact_repo, contact_id, payload)


@router.delete("/contacts/{contact_id}", status_code=204)
def delete_contact(contact_id: UUID, u: CurrentUser = Depends(requires("accounts.write")),
                   account_repo=Depends(get_account_repository),
                   contact_repo=Depends(get_contact_repository)):
    crm_service.delete_contact(u, account_repo, contact_repo, contact_id)


# ---- Assignments ----
@router.get("/accounts/{account_id}/assignments",
           response_model=list[crm_models.AccountAssignmentOut])
def list_assignments(account_id: str, u: CurrentUser = Depends(requires("platform.read")),
                     account_repo=Depends(get_account_repository),
                     assignment_repo=Depends(get_account_assignment_repository)):
    return crm_service.list_assignments(u, account_repo, assignment_repo, account_id)


@router.post("/accounts/{account_id}/assignments", status_code=201,
            response_model=crm_models.AccountAssignmentOut)
def add_assignment(account_id: str, payload: crm_models.AccountAssignmentCreate,
                   u: CurrentUser = Depends(requires("accounts.assign")),
                   account_repo=Depends(get_account_repository),
                   assignment_repo=Depends(get_account_assignment_repository)):
    return crm_service.add_assignment(u, account_repo, assignment_repo, account_id, payload)


@router.patch("/assignments/{assignment_id}", response_model=crm_models.AccountAssignmentOut)
def update_assignment(assignment_id: UUID, payload: crm_models.AccountAssignmentUpdate,
                      u: CurrentUser = Depends(requires("accounts.assign")),
                      account_repo=Depends(get_account_repository),
                      assignment_repo=Depends(get_account_assignment_repository)):
    return crm_service.update_assignment(u, account_repo, assignment_repo, assignment_id, payload)


# ---- Opportunities ----
@router.get("/opportunities", response_model=list[crm_models.OpportunityOut])
def list_opportunities(u: CurrentUser = Depends(requires("opportunities.read")),
                       opportunity_repo=Depends(get_opportunity_repository)):
    return crm_service.list_opportunities(u, opportunity_repo)


@router.post("/opportunities", status_code=201, response_model=crm_models.OpportunityOut)
def create_opportunity(payload: crm_models.OpportunityCreate,
                       u: CurrentUser = Depends(requires("opportunities.create")),
                       account_repo=Depends(get_account_repository),
                       opportunity_repo=Depends(get_opportunity_repository),
                       asset_repo=Depends(get_asset_repository)):
    return crm_service.create_opportunity(u, account_repo, opportunity_repo, payload, asset_repo)


@router.get("/opportunities/{opportunity_id}", response_model=crm_models.OpportunityOut)
def get_opportunity(opportunity_id: str, u: CurrentUser = Depends(requires("opportunities.read")),
                    opportunity_repo=Depends(get_opportunity_repository)):
    return crm_service.get_opportunity(u, opportunity_repo, opportunity_id)


@router.patch("/opportunities/{opportunity_id}", response_model=crm_models.OpportunityOut)
def update_opportunity(opportunity_id: str, payload: crm_models.OpportunityUpdate,
                       u: CurrentUser = Depends(requires("opportunities.edit")),
                       opportunity_repo=Depends(get_opportunity_repository)):
    return crm_service.update_opportunity(u, opportunity_repo, opportunity_id, payload)


@router.delete("/opportunities/{opportunity_id}", status_code=204)
def delete_opportunity(opportunity_id: str, u: CurrentUser = Depends(requires("opportunities.delete")),
                       opportunity_repo=Depends(get_opportunity_repository)):
    crm_service.delete_opportunity(u, opportunity_repo, opportunity_id)


# ---- Opportunity documents ----
@router.get("/opportunities/{opportunity_id}/documents",
           response_model=list[crm_models.OpportunityDocumentOut])
def list_opportunity_documents(opportunity_id: str, u: CurrentUser = Depends(requires("platform.read")),
                               opportunity_repo=Depends(get_opportunity_repository),
                               document_repo=Depends(get_opportunity_document_repository)):
    return crm_service.list_opportunity_documents(u, opportunity_repo, document_repo, opportunity_id)


@router.post("/opportunities/{opportunity_id}/documents", status_code=201,
            response_model=crm_models.OpportunityDocumentOut)
def add_opportunity_document(opportunity_id: str, payload: crm_models.OpportunityDocumentCreate,
                             u: CurrentUser = Depends(requires("opportunities.write")),
                             opportunity_repo=Depends(get_opportunity_repository),
                             document_repo=Depends(get_opportunity_document_repository)):
    return crm_service.add_opportunity_document(u, opportunity_repo, document_repo,
                                                opportunity_id, payload)


@router.patch("/opportunity-documents/{doc_id}", response_model=crm_models.OpportunityDocumentOut)
def update_opportunity_document(doc_id: UUID, payload: crm_models.OpportunityDocumentUpdate,
                                u: CurrentUser = Depends(requires("opportunities.write")),
                                opportunity_repo=Depends(get_opportunity_repository),
                                document_repo=Depends(get_opportunity_document_repository)):
    return crm_service.update_opportunity_document(u, opportunity_repo, document_repo, doc_id, payload)


# ---- Campaigns ----
@router.get("/campaigns", response_model=list[crm_models.CampaignOut])
def list_campaigns(u: CurrentUser = Depends(requires("platform.read")),
                   repo=Depends(get_campaign_repository)):
    return crm_service.list_campaigns(u, repo)


@router.post("/campaigns", status_code=201, response_model=crm_models.CampaignOut)
def create_campaign(payload: crm_models.CampaignCreate,
                    u: CurrentUser = Depends(requires("campaigns.write")),
                    repo=Depends(get_campaign_repository),
                    employees=Depends(get_employee_repository)):
    return crm_service.create_campaign(u, repo, employees, payload)


@router.get("/campaigns/{campaign_id}", response_model=crm_models.CampaignOut)
def get_campaign(campaign_id: UUID, u: CurrentUser = Depends(requires("platform.read")),
                 repo=Depends(get_campaign_repository)):
    return crm_service.get_campaign(u, repo, campaign_id)


@router.patch("/campaigns/{campaign_id}", response_model=crm_models.CampaignOut)
def update_campaign(campaign_id: UUID, payload: crm_models.CampaignUpdate,
                    u: CurrentUser = Depends(requires("campaigns.write")),
                    repo=Depends(get_campaign_repository),
                    employees=Depends(get_employee_repository)):
    return crm_service.update_campaign(u, repo, employees, campaign_id, payload)


@router.delete("/campaigns/{campaign_id}", status_code=204)
def delete_campaign(campaign_id: UUID, u: CurrentUser = Depends(requires("campaigns.write")),
                    repo=Depends(get_campaign_repository)):
    crm_service.delete_campaign(u, repo, campaign_id)


@router.post("/campaigns/{campaign_id}/send", response_model=crm_models.CampaignSendResult)
def send_campaign_email(campaign_id: UUID, payload: crm_models.CampaignSendRequest,
                        u: CurrentUser = Depends(requires("campaigns.write")),
                        campaign_repo=Depends(get_campaign_repository),
                        lead_repo=Depends(get_lead_repository),
                        comm_repo=Depends(get_communication_repository),
                        email_sender=Depends(get_email_sender)):
    return crm_service.send_campaign_email(
        u, campaign_repo, lead_repo, comm_repo, email_sender, campaign_id, payload)


# ---- Email-to-lead ----
# Triggered by a scheduler (Cloud Scheduler in the real deployment), not a
# logged-in employee — see require_email_intake_secret, not requires(...).
@router.post("/email-intake/poll", response_model=crm_models.EmailIntakeResult)
def poll_email_intake(_: None = Depends(require_email_intake_secret),
                      lead_repo=Depends(get_lead_repository),
                      employees=Depends(get_employee_repository),
                      rules_repo=Depends(get_lead_scoring_rule_repository),
                      comm_repo=Depends(get_communication_repository),
                      receiver=Depends(get_inbound_email_receiver),
                      cadence_template_repo=Depends(get_cadence_template_repository),
                      cadence_step_repo=Depends(get_cadence_step_repository),
                      cadence_enrollment_repo=Depends(get_lead_cadence_enrollment_repository),
                      cadence_task_repo=Depends(get_cadence_task_repository)):
    return crm_service.run_email_intake(
        lead_repo, employees, rules_repo, comm_repo, receiver,
        cadence_template_repo=cadence_template_repo, cadence_step_repo=cadence_step_repo,
        cadence_enrollment_repo=cadence_enrollment_repo, cadence_task_repo=cadence_task_repo,
    )


# ---- SMS-to-lead (inbound replies to a sent SMS) ----
# Triggered by Twilio's own webhook the moment a reply arrives at
# TWILIO_FROM_NUMBER — not a scheduler, not a logged-in employee. See
# require_twilio_signature, not requires(...): configure this URL as the
# "A MESSAGE COMES IN" webhook on that number in the Twilio Console
# (Phone Numbers -> Manage -> Active Numbers -> that number -> Messaging).
@router.post("/sms-intake/webhook", response_model=crm_models.SmsIntakeResult)
def receive_inbound_sms(form: dict[str, str] = Depends(require_twilio_signature),
                        lead_repo=Depends(get_lead_repository),
                        comm_repo=Depends(get_communication_repository)):
    return crm_service.process_inbound_sms(
        lead_repo, comm_repo,
        from_number=form.get("From", ""), body=form.get("Body", ""), message_sid=form.get("MessageSid", ""),
    )


# ---- WhatsApp-to-lead (inbound replies / delivery-status callbacks) ----
# Triggered by Twilio's own webhooks — not a scheduler, not a logged-in
# employee. See require_twilio_whatsapp_signature, not requires(...):
# configure these URLs on the WhatsApp Sender in the Twilio Console (or the
# Sandbox's "WHEN A MESSAGE COMES IN" / status callback settings).
@router.post("/whatsapp/webhook/inbound", response_model=activity_models.WhatsAppIntakeResult)
def receive_inbound_whatsapp(form: dict[str, str] = Depends(require_twilio_whatsapp_signature),
                             lead_repo=Depends(get_lead_repository),
                             comm_repo=Depends(get_communication_repository)):
    from_number = form.get("From", "").removeprefix("whatsapp:")
    return whatsapp_service.process_inbound_whatsapp(
        lead_repo, comm_repo,
        from_number=from_number, body=form.get("Body", ""), message_sid=form.get("MessageSid", ""),
    )


@router.post("/whatsapp/webhook/status")
def receive_whatsapp_status(form: dict[str, str] = Depends(require_twilio_whatsapp_signature),
                            comm_repo=Depends(get_communication_repository)):
    whatsapp_service.process_whatsapp_status_callback(
        comm_repo, message_sid=form.get("MessageSid", ""),
        message_status=form.get("MessageStatus", ""), error_code=form.get("ErrorCode") or None,
    )
    return {"ok": True}


# ---- Dial Pad browser calling (Twilio Voice) ----
# Triggered by Twilio's own webhooks — not a scheduler, not a logged-in
# employee. See require_twilio_voice_signature, not requires(...):
# configure /voice/webhook/connect as the Voice Request URL on the
# TwiML App (Console -> Voice -> TwiML Apps -> your app).
@router.post("/voice/webhook/connect")
def voice_webhook_connect(form: dict[str, str] = Depends(require_twilio_voice_signature),
                          lead_repo=Depends(get_lead_repository),
                          comm_repo=Depends(get_communication_repository)):
    twiml = voice_service.handle_voice_connect_webhook(
        lead_repo, comm_repo,
        parent_call_sid=form.get("CallSid", ""), from_field=form.get("From", ""),
        to_number=form.get("To", ""), lead_id_raw=form.get("LeadId", ""),
    )
    return Response(content=twiml, media_type="application/xml")


@router.post("/voice/webhook/status")
def voice_webhook_status(form: dict[str, str] = Depends(require_twilio_voice_signature),
                         comm_repo=Depends(get_communication_repository)):
    voice_service.process_voice_status_callback(
        comm_repo, call_sid=form.get("CallSid", ""), parent_call_sid=form.get("ParentCallSid") or None,
        call_status=form.get("CallStatus", ""), call_duration=form.get("CallDuration"),
        error_code=form.get("ErrorCode") or None,
    )
    return {"ok": True}


# ---- Leads ----
@router.get("/leads", response_model=list[crm_models.LeadOut])
def list_leads(
    campaign_id: UUID | None = Query(default=None),
    industry: str | None = Query(default=None),
    status: str | None = Query(default=None),
    owner_employee_id: UUID | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    u: CurrentUser = Depends(requires("leads.read")),
    repo=Depends(get_lead_repository),
):
    return crm_service.list_leads(u, repo, campaign_id=campaign_id, industry=industry, status=status,
                                  owner_employee_id=owner_employee_id, date_from=date_from, date_to=date_to)


@router.post("/leads", status_code=201, response_model=crm_models.LeadOut)
def create_lead(payload: crm_models.LeadCreate,
                u: CurrentUser = Depends(requires("leads.create")),
                repo=Depends(get_lead_repository),
                employees=Depends(get_employee_repository),
                rules_repo=Depends(get_lead_scoring_rule_repository),
                account_repo=Depends(get_account_repository),
                cadence_template_repo=Depends(get_cadence_template_repository),
                cadence_step_repo=Depends(get_cadence_step_repository),
                cadence_enrollment_repo=Depends(get_lead_cadence_enrollment_repository),
                cadence_task_repo=Depends(get_cadence_task_repository)):
    return crm_service.create_lead(
        u, repo, employees, rules_repo, payload, account_repo,
        cadence_template_repo=cadence_template_repo, cadence_step_repo=cadence_step_repo,
        cadence_enrollment_repo=cadence_enrollment_repo, cadence_task_repo=cadence_task_repo,
    )


@router.get("/leads/{lead_id}", response_model=crm_models.LeadOut)
def get_lead(lead_id: UUID, u: CurrentUser = Depends(requires("leads.read")),
            repo=Depends(get_lead_repository)):
    return crm_service.get_lead(u, repo, lead_id)


@router.get("/leads/{lead_id}/score-breakdown", response_model=list[crm_models.LeadScoreBreakdownEntry])
def get_lead_score_breakdown(lead_id: UUID, u: CurrentUser = Depends(requires("platform.read")),
                             repo=Depends(get_lead_repository),
                             rules_repo=Depends(get_lead_scoring_rule_repository)):
    return crm_service.get_lead_score_breakdown(u, repo, rules_repo, lead_id)


@router.patch("/leads/{lead_id}", response_model=crm_models.LeadOut)
def update_lead(lead_id: UUID, payload: crm_models.LeadUpdate,
                u: CurrentUser = Depends(requires("leads.edit")),
                repo=Depends(get_lead_repository),
                employees=Depends(get_employee_repository),
                rules_repo=Depends(get_lead_scoring_rule_repository),
                account_repo=Depends(get_account_repository)):
    return crm_service.update_lead(u, repo, employees, rules_repo, lead_id, payload, account_repo)


@router.delete("/leads/{lead_id}", status_code=204)
def delete_lead(lead_id: UUID, u: CurrentUser = Depends(requires("leads.delete")),
                repo=Depends(get_lead_repository)):
    crm_service.delete_lead(u, repo, lead_id)


@router.post("/leads/{lead_id}/flag-hot", response_model=crm_models.LeadOut)
def flag_lead_hot(lead_id: UUID, u: CurrentUser = Depends(requires("leads.flag_hot")),
                  repo=Depends(get_lead_repository),
                  notification_repo=Depends(get_notification_repository)):
    return crm_service.flag_lead_hot(u, repo, notification_repo, lead_id)


@router.post("/leads/{lead_id}/convert", response_model=crm_models.LeadOut)
def convert_lead(lead_id: UUID, payload: crm_models.LeadConvertRequest,
                 u: CurrentUser = Depends(requires("leads.convert")),
                 lead_repo=Depends(get_lead_repository),
                 account_repo=Depends(get_account_repository),
                 contact_repo=Depends(get_contact_repository),
                 opportunity_repo=Depends(get_opportunity_repository),
                 employees=Depends(get_employee_repository)):
    return crm_service.convert_lead(u, lead_repo, account_repo, contact_repo,
                                    opportunity_repo, employees, lead_id, payload)


# ---- Pulse: signal sourcing, Radar worklist, next-best-action ----
@router.get("/pulse/radar", response_model=list[crm_models.RadarRow])
def get_radar(
    mine: bool = Query(default=False, description="Only leads owned by the caller"),
    practice: str | None = Query(default=None, description="Filter to one recommended practice"),
    min_score: int = Query(default=0, ge=0),
    u: CurrentUser = Depends(requires("leads.read")),
    lead_repo=Depends(get_lead_repository),
    signal_repo=Depends(get_signal_repository),
):
    return crm_service.get_radar(u, lead_repo, signal_repo, mine=mine, practice=practice, min_score=min_score)


@router.post("/pulse/ingest", response_model=crm_models.SignalIngestResult)
def ingest_signals(
    since_days: int = Query(default=30, ge=1, le=365),
    u: CurrentUser = Depends(requires("leads.write")),
    lead_repo=Depends(get_lead_repository),
    signal_repo=Depends(get_signal_repository),
    rules_repo=Depends(get_lead_scoring_rule_repository),
):
    return crm_service.ingest_signals(u, lead_repo, signal_repo, rules_repo, since_days=since_days)


@router.get("/leads/{lead_id}/signals", response_model=list[crm_models.SignalOut])
def list_lead_signals(lead_id: UUID, u: CurrentUser = Depends(requires("leads.read")),
                      lead_repo=Depends(get_lead_repository),
                      signal_repo=Depends(get_signal_repository)):
    return crm_service.list_lead_signals(u, lead_repo, signal_repo, lead_id)


@router.post("/leads/{lead_id}/next-best-action", response_model=crm_models.NextBestActionOut)
def generate_next_best_action(
    lead_id: UUID, u: CurrentUser = Depends(requires("leads.write")),
    lead_repo=Depends(get_lead_repository),
    signal_repo=Depends(get_signal_repository),
    cadence_template_repo=Depends(get_cadence_template_repository),
    llm_client=Depends(get_optional_llm_client),
):
    return crm_service.generate_next_best_action(
        u, lead_repo, signal_repo, cadence_template_repo, llm_client, lead_id)


# ---- Lead scoring rules ----
@router.get("/lead-scoring-rules", response_model=list[crm_models.LeadScoringRuleOut])
def list_lead_scoring_rules(u: CurrentUser = Depends(requires("platform.read")),
                            repo=Depends(get_lead_scoring_rule_repository)):
    return crm_service.list_lead_scoring_rules(u, repo)


@router.post("/lead-scoring-rules", status_code=201, response_model=crm_models.LeadScoringRuleOut)
def create_lead_scoring_rule(payload: crm_models.LeadScoringRuleCreate,
                             u: CurrentUser = Depends(requires("lead_scoring_rules.write")),
                             repo=Depends(get_lead_scoring_rule_repository)):
    return crm_service.create_lead_scoring_rule(u, repo, payload)


@router.get("/lead-scoring-rules/{rule_id}", response_model=crm_models.LeadScoringRuleOut)
def get_lead_scoring_rule(rule_id: UUID, u: CurrentUser = Depends(requires("platform.read")),
                          repo=Depends(get_lead_scoring_rule_repository)):
    return crm_service.get_lead_scoring_rule(u, repo, rule_id)


@router.patch("/lead-scoring-rules/{rule_id}", response_model=crm_models.LeadScoringRuleOut)
def update_lead_scoring_rule(rule_id: UUID, payload: crm_models.LeadScoringRuleUpdate,
                             u: CurrentUser = Depends(requires("lead_scoring_rules.write")),
                             repo=Depends(get_lead_scoring_rule_repository)):
    return crm_service.update_lead_scoring_rule(u, repo, rule_id, payload)


@router.delete("/lead-scoring-rules/{rule_id}", status_code=204)
def delete_lead_scoring_rule(rule_id: UUID, u: CurrentUser = Depends(requires("lead_scoring_rules.write")),
                             repo=Depends(get_lead_scoring_rule_repository)):
    crm_service.delete_lead_scoring_rule(u, repo, rule_id)


# ---- Field-Level Security ----
@router.get("/field-permissions", response_model=list[crm_models.FieldPermissionEntry])
def list_field_permissions(object_name: str = Query(...),
                           u: CurrentUser = Depends(requires("field_permissions.write")),
                           repo=Depends(get_field_permission_repository)):
    return crm_service.list_field_permissions(u, repo, object_name)


@router.put("/field-permissions", response_model=list[crm_models.FieldPermissionEntry])
def save_field_permissions(payload: crm_models.FieldPermissionSaveRequest,
                           u: CurrentUser = Depends(requires("field_permissions.write")),
                           repo=Depends(get_field_permission_repository)):
    return crm_service.save_field_permissions(u, repo, payload)


@router.get("/field-permissions/effective", response_model=dict[str, crm_models.EffectiveFieldPermission])
def get_effective_field_permissions(object_name: str = Query(...),
                                    u: CurrentUser = Depends(requires("platform.read")),
                                    repo=Depends(get_field_permission_repository)):
    return crm_service.get_effective_field_permissions(u, repo, object_name)


# ---- Organization-Wide Defaults ----
# No /admin/ prefix — that's reserved for admin_routes.py's own routes
# (employees/teams/lookups/profiles/capabilities). This mirrors
# /field-permissions immediately above: admin-only-in-practice CRM config,
# gated by capability rather than by path, living in this module because its
# model/service/repository do (see crm_models.OrgWideDefault).
@router.get("/org-wide-defaults", response_model=crm_models.OrgWideDefaultsOut)
def get_org_wide_defaults(u: CurrentUser = Depends(requires("org_wide_defaults.write")),
                         repo=Depends(get_org_wide_default_repository)):
    return crm_service.get_org_wide_defaults(u, repo)


@router.put("/org-wide-defaults", response_model=crm_models.OrgWideDefaultsOut)
def save_org_wide_defaults(payload: crm_models.OrgWideDefaultsSaveRequest,
                          u: CurrentUser = Depends(requires("org_wide_defaults.write")),
                          repo=Depends(get_org_wide_default_repository)):
    return crm_service.save_org_wide_defaults(u, repo, payload)


# ---- Record Sharing ----
# User-based sharing on top of OWD/ownership — see
# services/record_access_service.py / crm_service.create_record_share().
# Gated by record_shares.write (broader than org_wide_defaults.write —
# sharing an individual record you can already edit is a day-to-day working
# action, not global config) PLUS a per-record EDIT check inside the service
# so a caller can never grant access they don't themselves have.
@router.get("/record-shares", response_model=list[crm_models.RecordShareOut])
def list_record_shares(object_name: str = Query(...), record_id: str = Query(...),
                       u: CurrentUser = Depends(requires("record_shares.write")),
                       share_repo=Depends(get_record_share_repository),
                       lead_repo=Depends(get_lead_repository),
                       account_repo=Depends(get_account_repository),
                       contact_repo=Depends(get_contact_repository),
                       opportunity_repo=Depends(get_opportunity_repository),
                       campaign_repo=Depends(get_campaign_repository)):
    return crm_service.list_record_shares(
        u, share_repo, object_name.upper(), record_id,
        lead_repo=lead_repo, account_repo=account_repo, contact_repo=contact_repo,
        opportunity_repo=opportunity_repo, campaign_repo=campaign_repo)


@router.post("/record-shares", status_code=201, response_model=crm_models.RecordShareOut)
def create_record_share(payload: crm_models.RecordShareCreate,
                        u: CurrentUser = Depends(requires("record_shares.write")),
                        share_repo=Depends(get_record_share_repository),
                        employees=Depends(get_employee_repository),
                        lead_repo=Depends(get_lead_repository),
                        account_repo=Depends(get_account_repository),
                        contact_repo=Depends(get_contact_repository),
                        opportunity_repo=Depends(get_opportunity_repository),
                        campaign_repo=Depends(get_campaign_repository)):
    return crm_service.create_record_share(
        u, share_repo, employees, payload,
        lead_repo=lead_repo, account_repo=account_repo, contact_repo=contact_repo,
        opportunity_repo=opportunity_repo, campaign_repo=campaign_repo)


@router.delete("/record-shares/{share_id}", status_code=204)
def delete_record_share(share_id: UUID, u: CurrentUser = Depends(requires("record_shares.write")),
                        share_repo=Depends(get_record_share_repository),
                        lead_repo=Depends(get_lead_repository),
                        account_repo=Depends(get_account_repository),
                        contact_repo=Depends(get_contact_repository),
                        opportunity_repo=Depends(get_opportunity_repository),
                        campaign_repo=Depends(get_campaign_repository)):
    crm_service.delete_record_share(
        u, share_repo, share_id,
        lead_repo=lead_repo, account_repo=account_repo, contact_repo=contact_repo,
        opportunity_repo=opportunity_repo, campaign_repo=campaign_repo)


# ---- Product catalog ----
@router.get("/products", response_model=list[crm_models.ProductOut])
def list_products(u: CurrentUser = Depends(requires("platform.read")),
                  repo=Depends(get_product_repository)):
    return crm_service.list_products(u, repo)


@router.post("/products", status_code=201, response_model=crm_models.ProductOut)
def create_product(payload: crm_models.ProductCreate,
                   u: CurrentUser = Depends(requires("products.write")),
                   repo=Depends(get_product_repository)):
    return crm_service.create_product(u, repo, payload)


@router.get("/products/{product_id}", response_model=crm_models.ProductOut)
def get_product(product_id: UUID, u: CurrentUser = Depends(requires("platform.read")),
                repo=Depends(get_product_repository)):
    return crm_service.get_product(u, repo, product_id)


@router.patch("/products/{product_id}", response_model=crm_models.ProductOut)
def update_product(product_id: UUID, payload: crm_models.ProductUpdate,
                   u: CurrentUser = Depends(requires("products.write")),
                   repo=Depends(get_product_repository)):
    return crm_service.update_product(u, repo, product_id, payload)


@router.delete("/products/{product_id}", status_code=204)
def delete_product(product_id: UUID, u: CurrentUser = Depends(requires("products.write")),
                   repo=Depends(get_product_repository)):
    crm_service.delete_product(u, repo, product_id)


# ---- Sales Cadence ----
@router.get("/cadence-templates", response_model=list[crm_models.CadenceTemplateOut])
def list_cadence_templates(u: CurrentUser = Depends(requires("platform.read")),
                           template_repo=Depends(get_cadence_template_repository),
                           step_repo=Depends(get_cadence_step_repository)):
    return crm_service.list_cadence_templates(u, template_repo, step_repo)


@router.post("/cadence-templates", status_code=201, response_model=crm_models.CadenceTemplateOut)
def create_cadence_template(payload: crm_models.CadenceTemplateCreate,
                            u: CurrentUser = Depends(requires("cadence_templates.write")),
                            template_repo=Depends(get_cadence_template_repository)):
    return crm_service.create_cadence_template(u, template_repo, payload)


@router.get("/cadence-templates/{template_id}", response_model=crm_models.CadenceTemplateOut)
def get_cadence_template(template_id: UUID, u: CurrentUser = Depends(requires("platform.read")),
                         template_repo=Depends(get_cadence_template_repository),
                         step_repo=Depends(get_cadence_step_repository)):
    return crm_service.get_cadence_template(u, template_repo, step_repo, template_id)


@router.patch("/cadence-templates/{template_id}", response_model=crm_models.CadenceTemplateOut)
def update_cadence_template(template_id: UUID, payload: crm_models.CadenceTemplateUpdate,
                            u: CurrentUser = Depends(requires("cadence_templates.write")),
                            template_repo=Depends(get_cadence_template_repository),
                            step_repo=Depends(get_cadence_step_repository)):
    return crm_service.update_cadence_template(u, template_repo, step_repo, template_id, payload)


@router.post("/cadence-templates/{template_id}/steps", status_code=201, response_model=crm_models.CadenceStepOut)
def add_cadence_step(template_id: UUID, payload: crm_models.CadenceStepCreate,
                     u: CurrentUser = Depends(requires("cadence_templates.write")),
                     template_repo=Depends(get_cadence_template_repository),
                     step_repo=Depends(get_cadence_step_repository)):
    return crm_service.add_cadence_step(u, template_repo, step_repo, template_id, payload)


@router.patch("/cadence-steps/{step_id}", response_model=crm_models.CadenceStepOut)
def update_cadence_step(step_id: UUID, payload: crm_models.CadenceStepUpdate,
                        u: CurrentUser = Depends(requires("cadence_templates.write")),
                        step_repo=Depends(get_cadence_step_repository)):
    return crm_service.update_cadence_step(u, step_repo, step_id, payload)


@router.delete("/cadence-steps/{step_id}", status_code=204)
def delete_cadence_step(step_id: UUID, u: CurrentUser = Depends(requires("cadence_templates.write")),
                        step_repo=Depends(get_cadence_step_repository)):
    crm_service.delete_cadence_step(u, step_repo, step_id)


@router.post("/leads/{lead_id}/cadence/enroll", status_code=201,
            response_model=crm_models.LeadCadenceEnrollmentDetailOut)
def enroll_lead_in_cadence(lead_id: UUID, payload: crm_models.LeadCadenceEnrollRequest,
                           u: CurrentUser = Depends(requires("cadences.enroll")),
                           lead_repo=Depends(get_lead_repository),
                           template_repo=Depends(get_cadence_template_repository),
                           step_repo=Depends(get_cadence_step_repository),
                           enrollment_repo=Depends(get_lead_cadence_enrollment_repository),
                           task_repo=Depends(get_cadence_task_repository),
                           employees=Depends(get_employee_repository)):
    return crm_service.enroll_lead_in_cadence(
        u, lead_repo, template_repo, step_repo, enrollment_repo, task_repo, employees, lead_id, payload)


@router.get("/leads/{lead_id}/cadence", response_model=crm_models.LeadCadenceEnrollmentDetailOut)
def get_lead_cadence(lead_id: UUID, u: CurrentUser = Depends(requires("platform.read")),
                     lead_repo=Depends(get_lead_repository),
                     enrollment_repo=Depends(get_lead_cadence_enrollment_repository),
                     task_repo=Depends(get_cadence_task_repository),
                     step_repo=Depends(get_cadence_step_repository)):
    return crm_service.get_lead_cadence_detail(u, lead_repo, enrollment_repo, task_repo, step_repo, lead_id)


@router.post("/leads/{lead_id}/cadence/cancel", response_model=crm_models.LeadCadenceEnrollmentDetailOut)
def cancel_lead_cadence_enrollment(lead_id: UUID, u: CurrentUser = Depends(requires("cadences.enroll")),
                                   lead_repo=Depends(get_lead_repository),
                                   enrollment_repo=Depends(get_lead_cadence_enrollment_repository),
                                   task_repo=Depends(get_cadence_task_repository),
                                   step_repo=Depends(get_cadence_step_repository)):
    return crm_service.cancel_lead_cadence_enrollment(u, lead_repo, enrollment_repo, task_repo, step_repo, lead_id)


@router.post("/cadence-tasks/{task_id}/complete", response_model=crm_models.CadenceTaskOut)
def complete_cadence_task(task_id: UUID, payload: crm_models.CadenceTaskCompleteRequest,
                          u: CurrentUser = Depends(requires("cadences.enroll")),
                          lead_repo=Depends(get_lead_repository),
                          enrollment_repo=Depends(get_lead_cadence_enrollment_repository),
                          step_repo=Depends(get_cadence_step_repository),
                          task_repo=Depends(get_cadence_task_repository),
                          comm_repo=Depends(get_communication_repository)):
    return crm_service.complete_cadence_task(
        u, lead_repo, enrollment_repo, step_repo, task_repo, task_id, payload, comm_repo)


@router.get("/cadence-tasks/my", response_model=list[crm_models.CadenceTaskOut])
def list_my_cadence_tasks(u: CurrentUser = Depends(requires("platform.read")),
                          lead_repo=Depends(get_lead_repository),
                          enrollment_repo=Depends(get_lead_cadence_enrollment_repository),
                          task_repo=Depends(get_cadence_task_repository),
                          step_repo=Depends(get_cadence_step_repository)):
    return crm_service.list_my_cadence_tasks(u, lead_repo, enrollment_repo, task_repo, step_repo)


# ---- Cadence scheduler ----
# Triggered by a scheduler (Cloud Scheduler in the real deployment), not a
# logged-in employee — see require_cadence_scheduler_secret, not requires(...).
# Same shape as poll_email_intake above.
@router.post("/cadence/advance-due-steps", response_model=crm_models.CadenceSchedulerRunOut)
def advance_due_cadence_steps(_: None = Depends(require_cadence_scheduler_secret),
                              enrollment_repo=Depends(get_lead_cadence_enrollment_repository),
                              step_repo=Depends(get_cadence_step_repository),
                              task_repo=Depends(get_cadence_task_repository),
                              comm_repo=Depends(get_communication_repository)):
    return crm_service.advance_due_cadence_steps(enrollment_repo, step_repo, task_repo, comm_repo)


# ---- AI-assisted email drafting / call prep ----
@router.post("/leads/{lead_id}/email-draft", response_model=crm_models.EmailDraftOut)
def generate_email_draft(lead_id: UUID, u: CurrentUser = Depends(requires("leads.write")),
                         lead_repo=Depends(get_lead_repository),
                         comm_repo=Depends(get_communication_repository),
                         products_repo=Depends(get_product_repository),
                         llm_client=Depends(get_llm_client)):
    return crm_service.generate_email_draft(u, lead_repo, comm_repo, products_repo, llm_client, lead_id)


@router.post("/leads/{lead_id}/call-prep", response_model=crm_models.CallPrepOut)
def generate_call_prep(lead_id: UUID, u: CurrentUser = Depends(requires("leads.write")),
                       lead_repo=Depends(get_lead_repository),
                       comm_repo=Depends(get_communication_repository),
                       products_repo=Depends(get_product_repository),
                       llm_client=Depends(get_llm_client)):
    return crm_service.generate_call_prep(u, lead_repo, comm_repo, products_repo, llm_client, lead_id)


@router.post("/leads/{lead_id}/web-enrichment", response_model=crm_models.LeadWebEnrichmentOut)
def generate_web_enrichment(lead_id: UUID, u: CurrentUser = Depends(requires("leads.write")),
                            lead_repo=Depends(get_lead_repository),
                            rules_repo=Depends(get_lead_scoring_rule_repository),
                            llm_client=Depends(get_llm_client)):
    return crm_service.generate_web_lead_enrichment(u, lead_repo, rules_repo, llm_client, lead_id)
