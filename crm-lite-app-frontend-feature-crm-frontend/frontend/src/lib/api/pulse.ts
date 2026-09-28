import type { Api } from "./client";

/**
 * Wire types for the Pulse module (backend src/models/pulse_models.py *Out
 * schemas). Pulse is the intelligence layer on top of the existing CRM Lead
 * pipeline: verified external Signals feed a composite, decayed, graded lead
 * score and a dynamic Next-Best-Action, surfaced in the Radar worklist.
 *
 * These mirror what the API returns, exactly like ./crm.ts does for the CRM
 * module — same `useApi()`/bearer-token transport, same (api, ...args) call
 * convention.
 */

/** GET /leads/{id}/signals — one verified external signal on a lead. */
export interface SignalOut {
  id: string;
  lead_id: string | null;
  company_name: string;
  /** HIRING | RFP_TENDER | TECH_STACK | BUYER_INTENT | LEADERSHIP_MOVE |
   * FUNDING_MA | FILING_EARNINGS | WEB_EVENT (backend SIGNAL_TYPES). */
  type: string;
  source: string;
  summary: string;
  /** 0..1 raw signal confidence before time-decay. */
  strength: number;
  practice_hint: string | null;
  url: string | null;
  captured_at: string;
  /** Decayed 0..40 contribution this signal makes to the lead score. */
  score_points: number;
}

/** GET /pulse/radar — one prioritized worklist row (a lead + its top signal
 * + why-now + the recommended practice), ranked by the composite score. */
export interface RadarRow {
  lead_id: string;
  company_name: string;
  industry: string | null;
  annual_revenue: number | null;
  status: string;
  lead_score: number;
  /** A / B / C / D band derived from the composite score. */
  grade: string;
  signal_points: number;
  recommended_practice: string | null;
  why_now: string;
  top_signal: string | null;
  top_signal_age_days: number | null;
  signal_count: number;
  owner_employee_id: string | null;
}

/** POST /leads/{id}/next-best-action — the single best next move, grounded
 * in the lead's signals + score. `source` is "ai" when the LLM produced it,
 * "fallback" when it was derived deterministically (no AI key configured). */
export interface NextBestActionOut {
  lead_id: string;
  action: string;
  /** EMAIL | CALL | LINKEDIN (LeadCommunicationChannel). */
  channel: string;
  why_now: string;
  due_in_days: number;
  recommended_practice: string | null;
  suggested_cadence_template_id: string | null;
  source: string;
}

/** POST /pulse/ingest — summary of one sourcing run. */
export interface IngestResult {
  sources_run: string[];
  signals_ingested: number;
  leads_created: number;
  leads_updated: number;
  rescored: number;
}

export interface RadarParams {
  /** Only leads owned by the current user. */
  mine?: boolean;
  practice?: string;
  min_score?: number;
}

export function getRadar(api: Api, params: RadarParams = {}): Promise<RadarRow[]> {
  return api.get<RadarRow[]>("/pulse/radar", {
    mine: params.mine ? "true" : undefined,
    practice: params.practice || undefined,
    min_score: params.min_score || undefined,
  });
}

/** Run the external signal sources, create/update leads, and rescore. */
export function ingestSignals(api: Api, sinceDays = 30): Promise<IngestResult> {
  return api.post<IngestResult>(`/pulse/ingest?since_days=${sinceDays}`);
}

export function listLeadSignals(api: Api, leadId: string): Promise<SignalOut[]> {
  return api.get<SignalOut[]>(`/leads/${leadId}/signals`);
}

export function getNextBestAction(api: Api, leadId: string): Promise<NextBestActionOut> {
  return api.post<NextBestActionOut>(`/leads/${leadId}/next-best-action`);
}

// ---- Presentation helpers (shared by Radar + the Lead Signals panel) ----

export const SIGNAL_TYPE_LABEL: Record<string, string> = {
  HIRING: "Hiring",
  RFP_TENDER: "RFP / Tender",
  TECH_STACK: "Tech stack",
  BUYER_INTENT: "Buyer intent",
  LEADERSHIP_MOVE: "Leadership move",
  FUNDING_MA: "Funding / M&A",
  FILING_EARNINGS: "Filing / Earnings",
  WEB_EVENT: "Web event",
};

/** Badge colour per grade — reuses the design system's Badge variants. */
export function gradeVariant(grade: string): "green" | "blue" | "amber" | "gray" {
  if (grade === "A") return "green";
  if (grade === "B") return "blue";
  if (grade === "C") return "amber";
  return "gray";
}

export function channelLabel(channel: string): string {
  if (channel === "EMAIL") return "Email";
  if (channel === "CALL") return "Call";
  if (channel === "LINKEDIN") return "LinkedIn";
  return channel;
}

export function signalTypeLabel(type: string): string {
  return SIGNAL_TYPE_LABEL[type] ?? type;
}
