import type { Api } from "./client";

/** Wire types for the Delivery module's SOW sub-resources (src/models/delivery_models.py). */
export interface SowDetailOut {
  agreement_id: string;
  project_id: string;
  governing_msa_id: string;
  billing_model: string | null;
  total_value: number | null;
  currency: string | null;
  headcount: number | null;
  invoicing_frequency: string | null;
}

export interface SowDetailUpsertPayload {
  project_id: string;
  governing_msa_id: string;
  billing_model?: string | null;
  total_value?: number | null;
  currency?: string;
  headcount?: number | null;
  invoicing_frequency?: string | null;
}

export interface SowBudgetOut {
  id: string;
  agreement_id: string;
  amount: number;
  currency: string;
  alert_threshold_percents: string | null;
  effective_from: string;
  is_current: boolean;
  reason: string | null;
}

export interface SowBudgetRevisePayload {
  amount: number;
  currency?: string;
  alert_threshold_percents?: string | null;
  effective_from: string;
  reason: string;
}

export interface SowBudgetConsumptionOut {
  agreement_id: string;
  budget_amount: number | null;
  consumed: number;
  hours_logged: number;
  consumed_percent: number | null;
}

export interface SowRateCardOut {
  id: string;
  agreement_id: string;
  role_label: string;
  rate_per_hour: number;
  currency: string;
  effective_from: string;
  notes: string | null;
}

export interface SowRateCardCreatePayload {
  role_label: string;
  rate_per_hour: number;
  currency?: string;
  effective_from: string;
  notes?: string | null;
}

export type SowRateCardUpdatePayload = Partial<Omit<SowRateCardCreatePayload, "role_label" | "effective_from">>;

export interface SowTeamMemberOut {
  id: string;
  agreement_id: string;
  employee_id: string | null;
  external_name: string | null;
  rate_card_id: string | null;
  override_rate_per_hour: number | null;
  assigned_from: string;
  assigned_until: string | null;
}

export interface SowTeamMemberCreatePayload {
  employee_id?: string | null;
  external_name?: string | null;
  rate_card_id?: string | null;
  override_rate_per_hour?: number | null;
  assigned_from: string;
  assigned_until?: string | null;
}

export interface SowTeamMemberUpdatePayload {
  rate_card_id?: string | null;
  override_rate_per_hour?: number | null;
  assigned_until?: string | null;
}

export interface SowMilestoneOut {
  id: string;
  agreement_id: string;
  milestone_name: string;
  planned_date: string;
  actual_date: string | null;
  amount: number | null;
  status: string | null;
  invoiced_at: string | null;
  invoice_ref: string | null;
  notes: string | null;
}

export interface SowMilestoneCreatePayload {
  milestone_name: string;
  planned_date: string;
  amount?: number | null;
  notes?: string | null;
}

export interface SowMilestoneUpdatePayload {
  actual_date?: string | null;
  status?: string;
  invoiced_at?: string | null;
  invoice_ref?: string | null;
  amount?: number | null;
  notes?: string | null;
}

export interface SowTimesheetOut {
  id: string;
  sow_team_member_id: string;
  agreement_id: string;
  week_start_date: string;
  hours: number;
  status: string;
  submitted_by_employee_id: string;
  approved_by_employee_id: string | null;
  approved_at: string | null;
  notes: string | null;
}

export interface SowTimesheetCreatePayload {
  sow_team_member_id: string;
  agreement_id: string;
  week_start_date: string;
  hours: number;
  notes?: string | null;
}

export interface SowTimesheetUpdatePayload {
  hours?: number;
  notes?: string | null;
}

// ---- SOW detail ------------------------------------------------------------

export function getSowDetail(api: Api, agreementId: string): Promise<SowDetailOut> {
  return api.get<SowDetailOut>(`/agreements/${agreementId}/sow-detail`);
}

export function upsertSowDetail(
  api: Api,
  agreementId: string,
  payload: SowDetailUpsertPayload
): Promise<SowDetailOut> {
  return api.patch<SowDetailOut>(`/agreements/${agreementId}/sow-detail`, payload);
}

// ---- Budget (versioned) -----------------------------------------------------

export function getBudget(api: Api, agreementId: string): Promise<SowBudgetOut> {
  return api.get<SowBudgetOut>(`/agreements/${agreementId}/budget`);
}

export function reviseBudget(
  api: Api,
  agreementId: string,
  payload: SowBudgetRevisePayload
): Promise<SowBudgetOut> {
  return api.post<SowBudgetOut>(`/agreements/${agreementId}/budget`, payload);
}

export function getBudgetConsumption(api: Api, agreementId: string): Promise<SowBudgetConsumptionOut> {
  return api.get<SowBudgetConsumptionOut>(`/agreements/${agreementId}/budget/consumption`);
}

/** Bulk variant across every SOW in the caller's scope, in one request --
 * use this instead of calling getBudgetConsumption per agreement. */
export function listBudgetConsumption(api: Api): Promise<SowBudgetConsumptionOut[]> {
  return api.get<SowBudgetConsumptionOut[]>("/sow-budget-consumption");
}

// ---- Rate card --------------------------------------------------------------

export function listRateCards(api: Api, agreementId: string): Promise<SowRateCardOut[]> {
  return api.get<SowRateCardOut[]>(`/agreements/${agreementId}/rate-card`);
}

export function addRateCard(
  api: Api,
  agreementId: string,
  payload: SowRateCardCreatePayload
): Promise<SowRateCardOut> {
  return api.post<SowRateCardOut>(`/agreements/${agreementId}/rate-card`, payload);
}

export function updateRateCard(
  api: Api,
  rateId: string,
  patch: SowRateCardUpdatePayload
): Promise<SowRateCardOut> {
  return api.patch<SowRateCardOut>(`/rate-card/${rateId}`, patch);
}

// ---- Team ---------------------------------------------------------------------

export function listTeam(api: Api, agreementId: string): Promise<SowTeamMemberOut[]> {
  return api.get<SowTeamMemberOut[]>(`/agreements/${agreementId}/team`);
}

export function addTeamMember(
  api: Api,
  agreementId: string,
  payload: SowTeamMemberCreatePayload
): Promise<SowTeamMemberOut> {
  return api.post<SowTeamMemberOut>(`/agreements/${agreementId}/team`, payload);
}

export function updateTeamMember(
  api: Api,
  memberId: string,
  patch: SowTeamMemberUpdatePayload
): Promise<SowTeamMemberOut> {
  return api.patch<SowTeamMemberOut>(`/team-member/${memberId}`, patch);
}

// ---- Milestones ---------------------------------------------------------------

export function listMilestones(api: Api, agreementId: string): Promise<SowMilestoneOut[]> {
  return api.get<SowMilestoneOut[]>(`/agreements/${agreementId}/milestones`);
}

export function addMilestone(
  api: Api,
  agreementId: string,
  payload: SowMilestoneCreatePayload
): Promise<SowMilestoneOut> {
  return api.post<SowMilestoneOut>(`/agreements/${agreementId}/milestones`, payload);
}

export function updateMilestone(
  api: Api,
  milestoneId: string,
  patch: SowMilestoneUpdatePayload
): Promise<SowMilestoneOut> {
  return api.patch<SowMilestoneOut>(`/milestones/${milestoneId}`, patch);
}

// ---- Timesheets ---------------------------------------------------------------

export function listTimesheets(api: Api): Promise<SowTimesheetOut[]> {
  return api.get<SowTimesheetOut[]>("/timesheets");
}

export function submitTimesheet(api: Api, payload: SowTimesheetCreatePayload): Promise<SowTimesheetOut> {
  return api.post<SowTimesheetOut>("/timesheets", payload);
}

export function editTimesheet(
  api: Api,
  timesheetId: string,
  patch: SowTimesheetUpdatePayload
): Promise<SowTimesheetOut> {
  return api.patch<SowTimesheetOut>(`/timesheets/${timesheetId}`, patch);
}

export function approveTimesheet(api: Api, timesheetId: string): Promise<SowTimesheetOut> {
  return api.patch<SowTimesheetOut>(`/timesheets/${timesheetId}/approve`);
}

export function rejectTimesheet(api: Api, timesheetId: string): Promise<SowTimesheetOut> {
  return api.patch<SowTimesheetOut>(`/timesheets/${timesheetId}/reject`);
}

// ---- Assets, Orders & Revenue Recognition (read-only — created
// automatically when a milestone is marked INVOICED, see backend
// delivery_service.py) -------------------------------------------------------

export interface AssetOut {
  id: string;
  account_id: string;
  agreement_id: string;
  campaign_id: string | null;
  name: string;
  status: string;
  /** Set once a renewal/cross-sell Opportunity has been created against this Asset. */
  renewed_by_opportunity_id: string | null;
}

export interface OrderOut {
  id: string;
  account_id: string;
  agreement_id: string;
  asset_id: string;
  milestone_id: string;
  status: string;
  amount: number;
  currency: string;
  order_date: string;
}

export interface RevenueRecognitionEntryOut {
  id: string;
  order_id: string;
  asset_id: string;
  account_id: string;
  agreement_id: string;
  opportunity_id: string | null;
  campaign_id: string | null;
  recognized_amount: number;
  currency: string;
  recognized_at: string;
}

export function listAssets(api: Api, accountId: string): Promise<AssetOut[]> {
  return api.get<AssetOut[]>(`/accounts/${accountId}/assets`);
}

export function listOrders(api: Api, agreementId: string): Promise<OrderOut[]> {
  return api.get<OrderOut[]>(`/agreements/${agreementId}/orders`);
}

export function listRevenueRecognition(api: Api, agreementId: string): Promise<RevenueRecognitionEntryOut[]> {
  return api.get<RevenueRecognitionEntryOut[]>(`/agreements/${agreementId}/revenue-recognition`);
}
