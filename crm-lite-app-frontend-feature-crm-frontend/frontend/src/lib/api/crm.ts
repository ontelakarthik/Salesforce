import type { Api } from "./client";

/**
 * Wire types for the CRM module (src/models/crm_models.py *Out schemas).
 * Distinct from types/schema.ts, which mirrors raw DB columns (e.g.
 * account_type_id) — these mirror what the API actually returns, where
 * lookup FKs are already resolved server-side to their code string
 * (e.g. account_type: "PROSPECT").
 */
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface AccountOut {
  id: string;
  // Required at create time — nullable here only because a Field-Level-
  // Security restriction can redact it (see LeadOut's identical comment).
  legal_name: string | null;
  account_type: string;
  account_site: string | null;
  industry: string | null;
  website: string | null;
  phone: string | null;
  address: string | null;
  shipping_address: string | null;
  // Structured Country -> State/Province (see src/lib/geo.ts), independent
  // for billing vs shipping — see backend crm_models.py's identical comment.
  billing_country: string | null;
  billing_state_province: string | null;
  // Derived server-side from billing_country + billing_state_province (see
  // backend crm_service._out()'s identical comment, and LeadOut.region) —
  // never sent by the client, only ever appears in responses.
  region: string | null;
  shipping_country: string | null;
  shipping_state_province: string | null;
  annual_revenue: number | null;
  num_employees: number | null;
  ownership: string | null;
  ticker_symbol: string | null;
  rating: string | null;
  account_number: string | null;
  sic_code: string | null;
  description: string | null;
  parent_account_id: string | null;
  owner_employee_id: string | null;
  // Sales Territory/Region (see backend admin_models.Territory) — a
  // business access-control concept, distinct from billing_country/region
  // above. Read-only: never sent by the client, always server-defaulted
  // from the owner's employee territory (backend crm_service.create_account()).
  territory: string | null;
  first_contact_at: string | null;
  promoted_to_client_at: string | null;
  // Computed server-side by services/record_access_service.py — never
  // re-derive OWD/ownership/sharing logic client-side from these.
  can_edit: boolean;
  can_delete: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface AccountUpdatePayload {
  legal_name?: string;
  account_site?: string | null;
  industry?: string | null;
  website?: string | null;
  phone?: string | null;
  address?: string | null;
  shipping_address?: string | null;
  billing_country?: string | null;
  billing_state_province?: string | null;
  shipping_country?: string | null;
  shipping_state_province?: string | null;
  annual_revenue?: number | null;
  num_employees?: number | null;
  ownership?: string | null;
  ticker_symbol?: string | null;
  rating?: string | null;
  account_number?: string | null;
  sic_code?: string | null;
  description?: string | null;
  parent_account_id?: string | null;
  owner_employee_id?: string | null;
}

export type AccountCreatePayload = Omit<AccountUpdatePayload, "legal_name"> & { legal_name: string };

export interface OpportunityOut {
  id: string;
  account_id: string;
  // Required at create time — nullable here only because a Field-Level-
  // Security restriction can redact it (see LeadOut's identical comment).
  name: string | null;
  stage: string;
  estimated_value: number | null;
  currency: string | null;
  expected_close_date: string | null;
  owner_employee_id: string | null;
  lost_reason: string | null;
  probability_percent: number | null;
  opportunity_type: string | null;
  next_step: string | null;
  description: string | null;
  lead_id: string | null;
  campaign_id: string | null;
  originating_asset_id: string | null;
  can_edit: boolean;
  can_delete: boolean;
}

export interface OpportunityCreatePayload {
  account_id: string;
  name: string;
  estimated_value?: number | null;
  currency?: string;
  expected_close_date?: string | null;
  owner_employee_id?: string | null;
  probability_percent?: number | null;
  opportunity_type?: string | null;
  next_step?: string | null;
  description?: string | null;
  /** Set to renew/cross-sell against an existing Asset — the Opportunity
   * auto-inherits the Asset's originating campaign_id server-side. */
  originating_asset_id?: string | null;
}

export interface OpportunityUpdatePayload {
  name?: string;
  stage?: string;
  estimated_value?: number | null;
  currency?: string;
  expected_close_date?: string | null;
  owner_employee_id?: string | null;
  lost_reason?: string | null;
  probability_percent?: number | null;
  opportunity_type?: string | null;
  next_step?: string | null;
  description?: string | null;
}

export interface OpportunityDocumentOut {
  id: string;
  opportunity_id: string;
  version_number: number;
  doc_type: string | null;
  status: string | null;
  sharepoint_item_id: string | null;
  sharepoint_url: string | null;
  filename: string | null;
  uploaded_at: string | null;
}

export interface OpportunityDocumentCreatePayload {
  doc_type?: string | null;
  filename?: string | null;
  sharepoint_item_id?: string | null;
  sharepoint_url?: string | null;
}

export interface ContactOut {
  id: string;
  account_id: string;
  contact_type: string;
  salutation: string | null;
  full_name: string;
  title: string | null;
  department: string | null;
  birthdate: string | null;
  email: string | null;
  phone: string | null;
  mobile_phone: string | null;
  home_phone: string | null;
  other_phone: string | null;
  assistant_name: string | null;
  assistant_phone: string | null;
  lead_source: string | null;
  address: string | null;
  other_address: string | null;
  description: string | null;
  reports_to_contact_id: string | null;
  is_primary: boolean;
  is_distribution_list: boolean;
  can_edit: boolean;
  can_delete: boolean;
}

export interface ContactCreatePayload {
  contact_type: string;
  salutation?: string | null;
  full_name: string;
  title?: string | null;
  department?: string | null;
  birthdate?: string | null;
  email?: string | null;
  phone?: string | null;
  mobile_phone?: string | null;
  home_phone?: string | null;
  other_phone?: string | null;
  assistant_name?: string | null;
  assistant_phone?: string | null;
  lead_source?: string | null;
  address?: string | null;
  other_address?: string | null;
  description?: string | null;
  reports_to_contact_id?: string | null;
  is_primary?: boolean;
  is_distribution_list?: boolean;
}

export type ContactUpdatePayload = Partial<ContactCreatePayload>;

export interface AccountAssignmentOut {
  id: string;
  account_id: string;
  employee_id: string | null;
  team_id: number | null;
  role: string;
  assigned_from: string;
  assigned_until: string | null;
}

export interface AccountAssignmentCreatePayload {
  employee_id?: string | null;
  team_id?: number | null;
  role: string;
  assigned_from: string;
  assigned_until?: string | null;
}

export interface AccountAssignmentUpdatePayload {
  role?: string;
  assigned_until?: string | null;
}

export interface ListAccountsParams {
  q?: string;
  account_type?: string;
  page?: number;
  page_size?: number;
  [key: string]: unknown;
}

// ---- Accounts (GET/PATCH /accounts, /accounts/{id}) --------------------

export function listAccounts(api: Api, params: ListAccountsParams = {}): Promise<Page<AccountOut>> {
  return api.get<Page<AccountOut>>("/accounts", params);
}

export function getAccount(api: Api, accountId: string): Promise<AccountOut> {
  return api.get<AccountOut>(`/accounts/${accountId}`);
}

export function updateAccount(
  api: Api,
  accountId: string,
  patch: AccountUpdatePayload
): Promise<AccountOut> {
  return api.patch<AccountOut>(`/accounts/${accountId}`, patch);
}

export function createAccount(api: Api, payload: AccountCreatePayload): Promise<AccountOut> {
  return api.post<AccountOut>("/accounts", payload);
}

export function promoteAccount(api: Api, accountId: string): Promise<AccountOut> {
  return api.post<AccountOut>(`/accounts/${accountId}/promote`);
}

export function deleteAccount(api: Api, accountId: string): Promise<void> {
  return api.del(`/accounts/${accountId}`);
}

// ---- Opportunities (GET/POST /opportunities, /opportunities/{id}) ---------

export function listOpportunities(api: Api): Promise<OpportunityOut[]> {
  return api.get<OpportunityOut[]>("/opportunities");
}

export function getOpportunity(api: Api, opportunityId: string): Promise<OpportunityOut> {
  return api.get<OpportunityOut>(`/opportunities/${opportunityId}`);
}

export function createOpportunity(
  api: Api,
  payload: OpportunityCreatePayload
): Promise<OpportunityOut> {
  return api.post<OpportunityOut>("/opportunities", payload);
}

export function updateOpportunity(
  api: Api,
  opportunityId: string,
  patch: OpportunityUpdatePayload
): Promise<OpportunityOut> {
  return api.patch<OpportunityOut>(`/opportunities/${opportunityId}`, patch);
}

export function deleteOpportunity(api: Api, opportunityId: string): Promise<void> {
  return api.del(`/opportunities/${opportunityId}`);
}

// ---- Opportunity documents (GET/POST .../documents) ------------------------

export function listOpportunityDocuments(api: Api, opportunityId: string): Promise<OpportunityDocumentOut[]> {
  return api.get<OpportunityDocumentOut[]>(`/opportunities/${opportunityId}/documents`);
}

export function addOpportunityDocument(
  api: Api,
  opportunityId: string,
  payload: OpportunityDocumentCreatePayload
): Promise<OpportunityDocumentOut> {
  return api.post<OpportunityDocumentOut>(`/opportunities/${opportunityId}/documents`, payload);
}

// ---- Contacts (GET/POST /accounts/{id}/contacts, PATCH /contacts/{id}) ---

export function listContacts(api: Api, accountId: string): Promise<ContactOut[]> {
  return api.get<ContactOut[]>(`/accounts/${accountId}/contacts`);
}

export function addContact(
  api: Api,
  accountId: string,
  payload: ContactCreatePayload
): Promise<ContactOut> {
  return api.post<ContactOut>(`/accounts/${accountId}/contacts`, payload);
}

export function updateContact(
  api: Api,
  contactId: string,
  patch: ContactUpdatePayload
): Promise<ContactOut> {
  return api.patch<ContactOut>(`/contacts/${contactId}`, patch);
}

export function deleteContact(api: Api, contactId: string): Promise<void> {
  return api.del(`/contacts/${contactId}`);
}

// ---- Assignments (GET/POST /accounts/{id}/assignments, PATCH /assignments/{id}) ----

export function listAssignments(api: Api, accountId: string): Promise<AccountAssignmentOut[]> {
  return api.get<AccountAssignmentOut[]>(`/accounts/${accountId}/assignments`);
}

export function addAssignment(
  api: Api,
  accountId: string,
  payload: AccountAssignmentCreatePayload
): Promise<AccountAssignmentOut> {
  return api.post<AccountAssignmentOut>(`/accounts/${accountId}/assignments`, payload);
}

export function updateAssignment(
  api: Api,
  assignmentId: string,
  patch: AccountAssignmentUpdatePayload
): Promise<AccountAssignmentOut> {
  return api.patch<AccountAssignmentOut>(`/assignments/${assignmentId}`, patch);
}

// ---- Campaigns (GET/POST /campaigns, /campaigns/{id}) ----------------------

export interface CampaignOut {
  id: string;
  name: string;
  campaign_type: string | null;
  status: string | null;
  start_date: string | null;
  end_date: string | null;
  description: string | null;
  budgeted_cost: number | null;
  actual_cost: number | null;
  expected_revenue: number | null;
  expected_response_pct: number | null;
  num_sent: number | null;
  parent_campaign_id: string | null;
  is_active: boolean;
  owner_employee_id: string | null;
  can_edit: boolean;
  can_delete: boolean;
}

export interface CampaignCreatePayload {
  name: string;
  campaign_type?: string | null;
  status?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  description?: string | null;
  budgeted_cost?: number | null;
  actual_cost?: number | null;
  expected_revenue?: number | null;
  expected_response_pct?: number | null;
  num_sent?: number | null;
  parent_campaign_id?: string | null;
  owner_employee_id?: string | null;
}

export type CampaignUpdatePayload = Partial<CampaignCreatePayload> & { is_active?: boolean };

export function listCampaigns(api: Api): Promise<CampaignOut[]> {
  return api.get<CampaignOut[]>("/campaigns");
}

export function getCampaign(api: Api, campaignId: string): Promise<CampaignOut> {
  return api.get<CampaignOut>(`/campaigns/${campaignId}`);
}

export function createCampaign(api: Api, payload: CampaignCreatePayload): Promise<CampaignOut> {
  return api.post<CampaignOut>("/campaigns", payload);
}

export function updateCampaign(
  api: Api,
  campaignId: string,
  patch: CampaignUpdatePayload
): Promise<CampaignOut> {
  return api.patch<CampaignOut>(`/campaigns/${campaignId}`, patch);
}

export function deleteCampaign(api: Api, campaignId: string): Promise<void> {
  return api.del(`/campaigns/${campaignId}`);
}

export interface CampaignSendResult {
  campaign_id: string;
  total_targeted: number;
  sent: number;
  skipped_no_email: number;
  skipped_opted_out: number;
  failed: number;
}

export function sendCampaignEmail(
  api: Api,
  campaignId: string,
  payload: { subject: string; body: string }
): Promise<CampaignSendResult> {
  return api.post<CampaignSendResult>(`/campaigns/${campaignId}/send`, payload);
}

// ---- Leads (GET/POST /leads, /leads/{id}, /leads/{id}/convert) -------------
// A Lead converts into an Account+Contact+Opportunity trio in one action —
// Account is this system's Account (see backend crm_models.py docstring).

export interface LeadOut {
  id: string;
  campaign_id: string | null;
  // Existing Account this Lead is associated with — optional (a Lead is
  // front-of-funnel and may not have one yet). Distinct from
  // converted_account_id below, which is only ever stamped by
  // POST /leads/{id}/convert. Selecting one in the UI is what drives the
  // Account -> Lead field auto-population (see NewLeadModal.tsx/Lead.tsx).
  account_id: string | null;
  // company_name/last_name/do_not_call/email_opt_out are required at create
  // time — the | null here is solely because a Field-Level-Security
  // restriction can redact them to null in a response for a role that
  // can't see them (see the backend's crm_service._redact()).
  company_name: string | null;
  salutation: string | null;
  first_name: string | null;
  last_name: string | null;
  title: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  mobile_phone: string | null;
  // WhatsApp (Twilio WhatsApp) — E.164 format, e.g. "+919876543210"; never
  // the "whatsapp:"-prefixed form Twilio itself uses on the wire.
  whatsapp_number: string | null;
  website: string | null;
  linkedin_url: string | null;
  industry: string | null;
  rating: string | null;
  annual_revenue: number | null;
  num_employees: number | null;
  address: string | null;
  // Structured Country -> State/Province (see src/lib/geo.ts). `region` is
  // never sent by the client — it's derived server-side from these two
  // (backend crm_service._lead_out()) and only ever appears in responses.
  country: string | null;
  state_province: string | null;
  region: string | null;
  description: string | null;
  do_not_call: boolean | null;
  email_opt_out: boolean | null;
  source: string | null;
  status: string;
  lead_score: number;
  owner_employee_id: string | null;
  // Sales Territory/Region — read-only, same treatment as AccountOut.territory.
  territory: string | null;
  converted_account_id: string | null;
  converted_contact_id: string | null;
  converted_opportunity_id: string | null;
  converted_at: string | null;
  can_edit: boolean;
  can_delete: boolean;
}

export interface LeadCreatePayload {
  company_name: string;
  account_id?: string | null;
  salutation?: string | null;
  first_name?: string | null;
  last_name: string;
  title?: string | null;
  // Required — core communication channel for a Lead; the cadence/
  // follow-up functionality depends on it (backend LeadCreate enforces the
  // same, both non-empty and a valid email format).
  contact_email: string;
  contact_phone?: string | null;
  mobile_phone?: string | null;
  website?: string | null;
  linkedin_url?: string | null;
  industry?: string | null;
  rating?: string | null;
  annual_revenue?: number | null;
  num_employees?: number | null;
  address?: string | null;
  country?: string | null;
  state_province?: string | null;
  description?: string | null;
  do_not_call?: boolean;
  email_opt_out?: boolean;
  campaign_id?: string | null;
  source?: string | null;
  owner_employee_id?: string | null;
}

export type LeadUpdatePayload = Partial<LeadCreatePayload> & { status?: string };

export interface LeadConvertPayload {
  opportunity_name: string;
  estimated_value?: number | null;
  currency?: string;
  expected_close_date?: string | null;
}

export function listLeads(api: Api): Promise<LeadOut[]> {
  return api.get<LeadOut[]>("/leads");
}

export function getLead(api: Api, leadId: string): Promise<LeadOut> {
  return api.get<LeadOut>(`/leads/${leadId}`);
}

export function createLead(api: Api, payload: LeadCreatePayload): Promise<LeadOut> {
  return api.post<LeadOut>("/leads", payload);
}

export function updateLead(api: Api, leadId: string, patch: LeadUpdatePayload): Promise<LeadOut> {
  return api.patch<LeadOut>(`/leads/${leadId}`, patch);
}

export function deleteLead(api: Api, leadId: string): Promise<void> {
  return api.del(`/leads/${leadId}`);
}

export function convertLead(api: Api, leadId: string, payload: LeadConvertPayload): Promise<LeadOut> {
  return api.post<LeadOut>(`/leads/${leadId}/convert`, payload);
}

/** LEADERSHIP's one narrow write path onto Lead — sets rating to HOT so a
 * manager can flag a lead as needing close attention without full edit
 * rights (see backend permissions.py's leads.flag_hot). */
export function flagLeadHot(api: Api, leadId: string): Promise<LeadOut> {
  return api.post<LeadOut>(`/leads/${leadId}/flag-hot`);
}

export interface LeadScoreBreakdownEntry {
  rule_id: string;
  name: string;
  points: number;
}

export function getLeadScoreBreakdown(api: Api, leadId: string): Promise<LeadScoreBreakdownEntry[]> {
  return api.get<LeadScoreBreakdownEntry[]>(`/leads/${leadId}/score-breakdown`);
}

// ---- Lead scoring rules (GET/POST /lead-scoring-rules, /lead-scoring-rules/{id}) ----
// Admin-managed config that drives Lead.lead_score (backend crm_service._compute_lead_score());
// field_name is validated server-side against a fixed allow-list of scorable Lead columns.

export const LEAD_SCORING_FIELDS = [
  "industry",
  "annual_revenue",
  "num_employees",
  "rating",
  "source",
  "email_opt_out",
  "do_not_call",
] as const;

export const LEAD_SCORING_OPERATORS = ["EQUALS", "GREATER_THAN", "LESS_THAN", "IS_SET", "CONTAINS"] as const;

export interface LeadScoringRuleOut {
  id: string;
  name: string;
  field_name: string;
  operator: string;
  comparison_value: string | null;
  points: number;
  is_active: boolean;
}

export interface LeadScoringRuleCreatePayload {
  name: string;
  field_name: string;
  operator: string;
  comparison_value?: string | null;
  points: number;
}

export type LeadScoringRuleUpdatePayload = Partial<LeadScoringRuleCreatePayload> & { is_active?: boolean };

export function listLeadScoringRules(api: Api): Promise<LeadScoringRuleOut[]> {
  return api.get<LeadScoringRuleOut[]>("/lead-scoring-rules");
}

export function createLeadScoringRule(
  api: Api,
  payload: LeadScoringRuleCreatePayload
): Promise<LeadScoringRuleOut> {
  return api.post<LeadScoringRuleOut>("/lead-scoring-rules", payload);
}

export function updateLeadScoringRule(
  api: Api,
  ruleId: string,
  patch: LeadScoringRuleUpdatePayload
): Promise<LeadScoringRuleOut> {
  return api.patch<LeadScoringRuleOut>(`/lead-scoring-rules/${ruleId}`, patch);
}

export function deleteLeadScoringRule(api: Api, ruleId: string): Promise<void> {
  return api.del(`/lead-scoring-rules/${ruleId}`);
}

// ---- Product catalog (GET/POST /products, /products/{id}) ----
// Admin-managed config that email-draft/call-prep match a researched lead
// against (backend crm_service._format_product_catalog()) instead of
// pitching generically.

export interface ProductOut {
  id: string;
  name: string;
  description: string;
  target_industry: string | null;
  is_active: boolean;
}

export interface ProductCreatePayload {
  name: string;
  description: string;
  target_industry?: string | null;
}

export type ProductUpdatePayload = Partial<ProductCreatePayload> & { is_active?: boolean };

export function listProducts(api: Api): Promise<ProductOut[]> {
  return api.get<ProductOut[]>("/products");
}

export function createProduct(api: Api, payload: ProductCreatePayload): Promise<ProductOut> {
  return api.post<ProductOut>("/products", payload);
}

export function updateProduct(
  api: Api,
  productId: string,
  patch: ProductUpdatePayload
): Promise<ProductOut> {
  return api.patch<ProductOut>(`/products/${productId}`, patch);
}

export function deleteProduct(api: Api, productId: string): Promise<void> {
  return api.del(`/products/${productId}`);
}

// ---- AI-assisted email drafting / call prep (POST /leads/{id}/email-draft, /call-prep) ----
// Both are best-effort: the backend returns a clear "not configured" error
// (not a 500) when COHERE_API_KEY is unset, rather than failing startup.

export interface EmailDraftOut {
  subject: string;
  body: string;
  model: string;
  grounded_in_replies: number;
  matched_products: string[];
}

export interface CallPrepOut {
  talking_points: string[];
  likely_objections: string[];
  opening_line: string;
  model: string;
  matched_products: string[];
}

export function generateEmailDraft(api: Api, leadId: string): Promise<EmailDraftOut> {
  return api.post<EmailDraftOut>(`/leads/${leadId}/email-draft`);
}

export function generateCallPrep(api: Api, leadId: string): Promise<CallPrepOut> {
  return api.post<CallPrepOut>(`/leads/${leadId}/call-prep`);
}
