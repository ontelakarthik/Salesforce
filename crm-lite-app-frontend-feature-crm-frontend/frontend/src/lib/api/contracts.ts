import type { Api } from "./client";

/** Wire types for the Contracts module (src/models/contracts_models.py). */
export interface AgreementOut {
  id: string;
  account_id: string;
  agreement_type: string;
  status: string;
  title: string;
  initiated_by_employee_id: string | null;
  effective_date: string | null;
  expiry_date: string | null;
  signed_at: string | null;
  signed_by_employee_id: string | null;
  supersedes_agreement_id: string | null;
  sla_due_at: string | null;
  sla_breached_at: string | null;
  sharepoint_folder_url: string | null;
  /** Salesforce Contract-standard fields — Company Signed By/Date is
   * signed_by_employee_id/signed_at above; Contract Number/Status are this
   * record's own id/status. */
  contract_term_months: number | null;
  owner_expiration_notice_days: number | null;
  customer_signed_contact_id: string | null;
  customer_signed_title: string | null;
  customer_signed_date: string | null;
  special_terms: string | null;
  billing_address: string | null;
}

export interface AgreementCreatePayload {
  account_id: string;
  agreement_type: string;
  title: string;
  effective_date?: string | null;
  expiry_date?: string | null;
  sharepoint_folder_url?: string | null;
  contract_term_months?: number | null;
  owner_expiration_notice_days?: number | null;
  customer_signed_contact_id?: string | null;
  customer_signed_title?: string | null;
  customer_signed_date?: string | null;
  special_terms?: string | null;
  billing_address?: string | null;
}

export interface AgreementUpdatePayload {
  title?: string;
  status?: string;
  effective_date?: string | null;
  expiry_date?: string | null;
  sharepoint_folder_url?: string | null;
  contract_term_months?: number | null;
  owner_expiration_notice_days?: number | null;
  customer_signed_contact_id?: string | null;
  customer_signed_title?: string | null;
  customer_signed_date?: string | null;
  special_terms?: string | null;
  billing_address?: string | null;
}

export interface AgreementClauseOut {
  id: string;
  agreement_id: string;
  section_ref: string | null;
  clause_text: string;
  is_flagged: boolean;
  flag_reason: string | null;
  policy_ref: string | null;
  resolution_status: string | null;
}

export interface AgreementClauseCreatePayload {
  section_ref?: string | null;
  clause_text: string;
  policy_ref?: string | null;
}

export interface AgreementClauseUpdatePayload {
  clause_text?: string;
  is_flagged?: boolean;
  flag_reason?: string | null;
  resolution_status?: string | null;
}

export interface AgreementDocumentOut {
  id: string;
  agreement_id: string;
  version_number: number;
  sharepoint_item_id: string | null;
  sharepoint_url: string | null;
  filename: string | null;
  content_type: string | null;
  size_bytes: number | null;
  uploaded_by_source: string | null;
  uploaded_at: string | null;
}

export interface AgreementDocumentCreatePayload {
  filename?: string | null;
  content_type?: string | null;
  size_bytes?: number | null;
  sharepoint_item_id?: string | null;
  sharepoint_url?: string | null;
}

export interface AgreementReviewOut {
  id: string;
  agreement_id: string;
  reviewer_type: string | null;
  reviewer_employee_id: string | null;
  summary: string | null;
  outcome: string | null;
  reviewed_at: string | null;
}

export interface AgreementReviewCreatePayload {
  reviewer_type?: string;
  summary?: string | null;
  outcome: string;
}

export interface AgreementNoteOut {
  id: string;
  agreement_id: string;
  note_text: string;
  created_at: string | null;
  created_by: string | null;
}

export interface AgreementNoteCreatePayload {
  note_text: string;
}

// ---- Agreements (GET/POST /agreements, /agreements/{id}) ------------------

export function listAgreements(api: Api): Promise<AgreementOut[]> {
  return api.get<AgreementOut[]>("/agreements");
}

export function getAgreement(api: Api, agreementId: string): Promise<AgreementOut> {
  return api.get<AgreementOut>(`/agreements/${agreementId}`);
}

export function createAgreement(api: Api, payload: AgreementCreatePayload): Promise<AgreementOut> {
  return api.post<AgreementOut>("/agreements", payload);
}

export function updateAgreement(
  api: Api,
  agreementId: string,
  patch: AgreementUpdatePayload
): Promise<AgreementOut> {
  return api.patch<AgreementOut>(`/agreements/${agreementId}`, patch);
}

export function sendAgreementForSignature(api: Api, agreementId: string): Promise<AgreementOut> {
  return api.post<AgreementOut>(`/agreements/${agreementId}/send-for-signature`);
}

export function signAgreement(api: Api, agreementId: string): Promise<AgreementOut> {
  return api.post<AgreementOut>(`/agreements/${agreementId}/sign`);
}

export function supersedeAgreement(
  api: Api,
  agreementId: string,
  payload: { title?: string; effective_date?: string | null; expiry_date?: string | null } = {}
): Promise<AgreementOut> {
  return api.post<AgreementOut>(`/agreements/${agreementId}/supersede`, payload);
}

// ---- Clauses (GET/POST .../clauses, PATCH /clauses/{id}) ------------------

export function listClauses(api: Api, agreementId: string): Promise<AgreementClauseOut[]> {
  return api.get<AgreementClauseOut[]>(`/agreements/${agreementId}/clauses`);
}

export function addClause(
  api: Api,
  agreementId: string,
  payload: AgreementClauseCreatePayload
): Promise<AgreementClauseOut> {
  return api.post<AgreementClauseOut>(`/agreements/${agreementId}/clauses`, payload);
}

export function updateClause(
  api: Api,
  clauseId: string,
  patch: AgreementClauseUpdatePayload
): Promise<AgreementClauseOut> {
  return api.patch<AgreementClauseOut>(`/clauses/${clauseId}`, patch);
}

// ---- Documents (GET/POST .../documents) -----------------------------------

export function listAgreementDocuments(api: Api, agreementId: string): Promise<AgreementDocumentOut[]> {
  return api.get<AgreementDocumentOut[]>(`/agreements/${agreementId}/documents`);
}

export function addAgreementDocument(
  api: Api,
  agreementId: string,
  payload: AgreementDocumentCreatePayload
): Promise<AgreementDocumentOut> {
  return api.post<AgreementDocumentOut>(`/agreements/${agreementId}/documents`, payload);
}

// ---- Reviews (GET/POST .../reviews) ----------------------------------------

export function listReviews(api: Api, agreementId: string): Promise<AgreementReviewOut[]> {
  return api.get<AgreementReviewOut[]>(`/agreements/${agreementId}/reviews`);
}

export function addReview(
  api: Api,
  agreementId: string,
  payload: AgreementReviewCreatePayload
): Promise<AgreementReviewOut> {
  return api.post<AgreementReviewOut>(`/agreements/${agreementId}/reviews`, payload);
}

// ---- Notes (GET/POST .../notes) --------------------------------------------

export function listNotes(api: Api, agreementId: string): Promise<AgreementNoteOut[]> {
  return api.get<AgreementNoteOut[]>(`/agreements/${agreementId}/notes`);
}

export function addNote(
  api: Api,
  agreementId: string,
  payload: AgreementNoteCreatePayload
): Promise<AgreementNoteOut> {
  return api.post<AgreementNoteOut>(`/agreements/${agreementId}/notes`, payload);
}
