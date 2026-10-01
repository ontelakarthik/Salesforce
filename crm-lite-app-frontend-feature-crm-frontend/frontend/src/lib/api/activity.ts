import type { Api } from "./client";

/** Wire types for the Activity module (src/models/activity_models.py). */
export interface NotificationOut {
  id: string;
  agreement_id: string | null;
  account_id: string | null;
  lead_id: string | null;
  recipient_employee_id: string | null;
  notification_type: string;
  severity: string;
  message: string | null;
  sent_at: string;
  acknowledged: boolean;
}

export function listNotifications(api: Api): Promise<NotificationOut[]> {
  return api.get<NotificationOut[]>("/notifications");
}

export function acknowledgeNotification(api: Api, notificationId: string): Promise<NotificationOut> {
  return api.patch<NotificationOut>(`/notifications/${notificationId}/acknowledge`);
}

export interface CommunicationOut {
  id: string;
  account_id: string | null;
  agreement_id: string | null;
  lead_id: string | null;
  received_via_team_id: number | null;
  direction: string;
  channel: string;
  subject: string | null;
  // Full message content — the email body (both directions) for EMAIL rows,
  // or free-text call notes for CALL rows kept separate from `subject`/`notes`.
  body: string | null;
  // Free-text notes on a logged Communication (e.g. Log a Call's Notes field).
  notes: string | null;
  from_address: string | null;
  to_recipients: string | null;
  cc_recipients: string | null;
  // Twilio's message SID for an SMS or WHATSAPP row.
  provider_message_id: string | null;
  occurred_at: string;
  source: string | null;
  call_duration_seconds: number | null;
  call_outcome: string | null;
  opened_at: string | null;
  replied_at: string | null;
  // Twilio delivery-status callback tracking (WhatsApp today) —
  // queued | sent | delivered | read | failed | undelivered.
  delivery_status: string | null;
  failure_code: string | null;
  whatsapp_template_id: string | null;
  template_variables: string | null;
  media_url: string | null;
  media_content_type: string | null;
  logged_by_employee_id: string | null;
}

export interface CommunicationCreatePayload {
  direction: string;
  channel: string;
  subject?: string | null;
  body?: string | null;
  notes?: string | null;
  from_address?: string | null;
  to_recipients?: string | null;
  cc_recipients?: string | null;
  occurred_at: string;
  call_duration_seconds?: number | null;
  call_outcome?: string | null;
}

export function listAccountCommunications(api: Api, accountId: string): Promise<CommunicationOut[]> {
  return api.get<CommunicationOut[]>(`/accounts/${accountId}/communications`);
}

export function addAccountCommunication(
  api: Api,
  accountId: string,
  payload: CommunicationCreatePayload
): Promise<CommunicationOut> {
  return api.post<CommunicationOut>(`/accounts/${accountId}/communications`, payload);
}

export function listAgreementCommunications(api: Api, agreementId: string): Promise<CommunicationOut[]> {
  return api.get<CommunicationOut[]>(`/agreements/${agreementId}/communications`);
}

export function addAgreementCommunication(
  api: Api,
  agreementId: string,
  payload: CommunicationCreatePayload
): Promise<CommunicationOut> {
  return api.post<CommunicationOut>(`/agreements/${agreementId}/communications`, payload);
}

// ---- Lead communications (GET/POST /leads/{id}/communications, .../send) ----
// send_lead_email actually sends the email (SMTP) and logs it as a Communication
// on success; add_lead_communication just records a manual entry (e.g. a call).

export function listLeadCommunications(api: Api, leadId: string): Promise<CommunicationOut[]> {
  return api.get<CommunicationOut[]>(`/leads/${leadId}/communications`);
}

export function addLeadCommunication(
  api: Api,
  leadId: string,
  payload: CommunicationCreatePayload
): Promise<CommunicationOut> {
  return api.post<CommunicationOut>(`/leads/${leadId}/communications`, payload);
}

export interface SendLeadEmailPayload {
  subject: string;
  body: string;
  to_address?: string | null;
}

/** to_address defaults server-side to the lead's own contact_email when omitted. */
export function sendLeadEmail(api: Api, leadId: string, payload: SendLeadEmailPayload): Promise<CommunicationOut> {
  return api.post<CommunicationOut>(`/leads/${leadId}/communications/send`, payload);
}

export interface SendLeadSmsPayload {
  message: string;
}

/** Sends via Twilio (src/services/sms_service.py) and logs it as a
 * Communication on success. Recipient defaults server-side to the lead's
 * contact_phone, falling back to mobile_phone. */
export function sendLeadSms(api: Api, leadId: string, payload: SendLeadSmsPayload): Promise<CommunicationOut> {
  return api.post<CommunicationOut>(`/leads/${leadId}/sms`, payload);
}

export interface SendLeadWhatsAppPayload {
  body: string;
}

/** Sends via Twilio WhatsApp (src/integrations/twilio_whatsapp.py) and logs
 * it as a Communication on success, mirroring sendLeadSms(). Recipient is
 * always the lead's own whatsapp_number — there is no override param. */
export function sendLeadWhatsApp(
  api: Api,
  leadId: string,
  payload: SendLeadWhatsAppPayload
): Promise<CommunicationOut> {
  return api.post<CommunicationOut>(`/leads/${leadId}/whatsapp`, payload);
}

export interface AuditLogOut {
  id: string;
  entity_type: string;
  entity_id: string;
  action: string;
  field_changed: string | null;
  old_value: string | null;
  new_value: string | null;
  performed_by_employee_id: string | null;
  performed_at: string;
}

export interface ListAuditParams {
  entity_type?: string;
  entity_id?: string;
  [key: string]: unknown;
}

export function listAudit(api: Api, params: ListAuditParams = {}): Promise<AuditLogOut[]> {
  return api.get<AuditLogOut[]>("/audit", params);
}
