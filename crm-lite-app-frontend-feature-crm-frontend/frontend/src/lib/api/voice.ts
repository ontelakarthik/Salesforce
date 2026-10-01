import type { Api } from "./client";
import type { CommunicationOut } from "./activity";

/** Wire types for the Dial Pad browser-calling feature (Twilio Voice) —
 * src/services/voice_service.py. */
export interface VoiceAccessTokenOut {
  token: string;
  identity: string;
}

/** A short-lived Twilio Voice Access Token for this lead — the browser's
 * Voice SDK uses it to register a Device and place one outgoing call. Never
 * a Twilio credential itself; those stay backend-only. */
export function getLeadVoiceToken(api: Api, leadId: string): Promise<VoiceAccessTokenOut> {
  return api.get<VoiceAccessTokenOut>(`/leads/${leadId}/voice-token`);
}

export interface UpdateCallNotesPayload {
  subject?: string | null;
  notes?: string | null;
}

/** The only fields still editable on a Dial-Pad-created CALL Communication
 * row — Outcome/Duration on that row come from Twilio's status callback,
 * not from this call. */
export function updateCallNotes(
  api: Api,
  leadId: string,
  commId: string,
  payload: UpdateCallNotesPayload
): Promise<CommunicationOut> {
  return api.post<CommunicationOut>(`/leads/${leadId}/communications/${commId}/call-notes`, payload);
}
