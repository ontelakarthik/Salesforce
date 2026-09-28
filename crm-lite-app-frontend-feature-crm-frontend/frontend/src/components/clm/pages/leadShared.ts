import type { BadgeVariant } from "../Badge";
import type { AccountOut, LeadOut } from "@/lib/api/crm";

export function leadFullName(lead: LeadOut): string {
  return [lead.salutation, lead.first_name, lead.last_name].filter(Boolean).join(" ");
}

/** Company-level Lead draft fields that get overwritten when a rep picks an
 * existing Account (see NewLeadModal.tsx/Lead.tsx) — every Account field
 * with a same-meaning counterpart on Lead (crm_models.py's LeadCreate/
 * AccountCreate). Person-level fields (name, title, email...) are never
 * touched here — Account selection speaks to the company, not the
 * individual contact. Billing country/state feed the Lead's own
 * country/state_province, same fields the Country/State/Region dropdowns
 * already use — this never bypasses or duplicates that logic, it only
 * supplies new values for the same draft fields. */
export interface LeadAccountFields {
  company_name: string;
  industry: string;
  website: string;
  contact_phone: string;
  address: string;
  country: string;
  state_province: string;
  annual_revenue: string;
  num_employees: string;
  rating: string;
}

export function leadFieldsFromAccount(account: AccountOut): LeadAccountFields {
  return {
    company_name: account.legal_name ?? "",
    industry: account.industry ?? "",
    website: account.website ?? "",
    contact_phone: account.phone ?? "",
    address: account.address ?? "",
    country: account.billing_country ?? "",
    state_province: account.billing_state_province ?? "",
    annual_revenue: account.annual_revenue != null ? String(account.annual_revenue) : "",
    num_employees: account.num_employees != null ? String(account.num_employees) : "",
    rating: account.rating ?? "",
  };
}

export const STATUS_BADGE: Record<string, BadgeVariant> = {
  NEW: "gray",
  ATTEMPTING_CONTACT: "amber",
  CONTACTED: "teal",
  QUALIFYING: "violet",
  QUALIFIED: "blue",
  NURTURING: "amber",
  UNQUALIFIED: "gray",
  DISQUALIFIED: "red",
  CONVERTED: "green",
};

// Mirrors backend crm_service._LEAD_TRANSITIONS exactly — CONVERTED only
// happens through the dedicated Convert action, never a plain status PATCH.
// The main path is NEW -> ATTEMPTING_CONTACT -> CONTACTED -> QUALIFYING ->
// QUALIFIED -> CONVERTED; NURTURING is a revisitable side branch reachable
// from (and able to return to) most active stages. UNQUALIFIED/
// DISQUALIFIED/CONVERTED are terminal.
export const LEAD_TRANSITIONS: Record<string, string[]> = {
  NEW: ["ATTEMPTING_CONTACT", "UNQUALIFIED", "DISQUALIFIED"],
  ATTEMPTING_CONTACT: ["CONTACTED", "NURTURING", "UNQUALIFIED", "DISQUALIFIED"],
  CONTACTED: ["QUALIFYING", "NURTURING", "UNQUALIFIED", "DISQUALIFIED"],
  QUALIFYING: ["QUALIFIED", "NURTURING", "UNQUALIFIED", "DISQUALIFIED"],
  QUALIFIED: ["NURTURING", "DISQUALIFIED"],
  NURTURING: ["CONTACTED", "QUALIFYING", "UNQUALIFIED", "DISQUALIFIED"],
  UNQUALIFIED: [],
  DISQUALIFIED: [],
  CONVERTED: [],
};

export const ACTION_LABEL: Record<string, string> = {
  ATTEMPTING_CONTACT: "Start attempting contact",
  CONTACTED: "Mark contacted",
  QUALIFYING: "Start qualifying",
  QUALIFIED: "Mark qualified",
  NURTURING: "Move to nurturing",
  UNQUALIFIED: "Mark unqualified",
  DISQUALIFIED: "Disqualify",
};

/** Shown on hover over each stage — the same copy everywhere a stage name
 * appears (the Lead detail Path bar, the status badge). */
export const STATUS_DESCRIPTION: Record<string, string> = {
  NEW: "Lead just entered the system, not yet touched. Auto-assigned on creation.",
  ATTEMPTING_CONTACT: "You've reached out (call/email/LinkedIn) but no two-way conversation yet.",
  CONTACTED: "Prospect has responded; a real conversation has started.",
  QUALIFYING: "You're assessing fit: budget, authority, need, timeline (BANT), or their tech stack, "
    + "project scope, and decision process.",
  QUALIFIED: "Confirmed fit and genuine intent. This is usually where a lead converts into an "
    + "opportunity/deal.",
  NURTURING: "Good fit but not ready now (no budget yet, future project, waiting on internal "
    + "approval). Stays warm for later.",
  UNQUALIFIED: "Not a fit (no need, no budget, wrong geography, or a competitor).",
  DISQUALIFIED: "Spam, students, job seekers, or bad-fit inquiries.",
  CONVERTED: "Became a real Account, Contact, and Opportunity.",
};

export const STATUS_LABEL: Record<string, string> = {
  NEW: "New",
  ATTEMPTING_CONTACT: "Attempting Contact",
  CONTACTED: "Contacted",
  QUALIFYING: "Qualifying",
  QUALIFIED: "Qualified (Opportunity)",
  NURTURING: "Nurturing",
  UNQUALIFIED: "Unqualified",
  DISQUALIFIED: "Disqualified / Junk",
  CONVERTED: "Converted",
};

/** Ordered "happy path" for the Lead detail page's Path/stage bar.
 * NURTURING/UNQUALIFIED/DISQUALIFIED are side-states, rendered as trailing
 * pills (like Opportunity's "Lost"), not part of this ordered sequence. */
export const LEAD_PATH_STAGES = ["NEW", "ATTEMPTING_CONTACT", "CONTACTED", "QUALIFYING", "QUALIFIED", "CONVERTED"] as const;

/** Side-exit states shown as trailing pills next to the main path bar. */
export const LEAD_SIDE_STATES = ["NURTURING", "UNQUALIFIED", "DISQUALIFIED"] as const;
