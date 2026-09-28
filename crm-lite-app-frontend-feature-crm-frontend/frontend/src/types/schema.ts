/**
 * TypeScript mirror of the CLM data model (v5, 29 tables) shown in the ER diagram.
 * Column names/types/nullability/PK/FK follow the diagram exactly. This is the
 * shared domain-model layer; page-local mock data should conform to these shapes
 * rather than inventing ad-hoc fields.
 *
 * Conventions: uuid/string PK -> string; int -> number; bool -> boolean;
 * date -> "YYYY-MM-DD"; datetime -> ISO 8601 string; decimal/bigint -> number.
 */

// ───────────────────────── Lookup tables ─────────────────────────

export interface AccountTypeLookup {
  id: number;
  code: "PROSPECT" | "CLIENT" | "PARTNER" | "VENDOR";
  display_name: string;
}

export interface AgreementTypeLookup {
  id: number;
  code: "NDA" | "MSA" | "SOW" | "RESELLER";
  display_name: string;
  default_sla_hours: number;
}

export interface AgreementStatusLookup {
  id: number;
  code:
    | "DRAFT"
    | "REQUESTED"
    | "UNDER_REVIEW"
    | "SENT_FOR_SIGNATURE"
    | "SIGNED"
    | "ACTIVE"
    | "EXPIRING_SOON"
    | "SUPERSEDED"
    | "TERMINATED"
    | "EXPIRED";
  display_name: string;
  is_terminal: boolean;
}

export interface ProjectStatusLookup {
  id: number;
  code: string;
  display_name: string;
  is_terminal: boolean;
}

export interface OpportunityStageLookup {
  id: number;
  code: "NEW" | "QUALIFIED" | "PROPOSAL" | "NEGOTIATION" | "WON" | "LOST";
  display_name: string;
  is_terminal: boolean;
}

export interface ContactTypeLookup {
  id: number;
  code: "BUSINESS" | "LEGAL" | "PROCUREMENT" | "FINANCE" | "TECHNICAL";
  display_name: string;
}

export interface RoleLookup {
  id: number;
  code: "SALES" | "ACCOUNT_EXEC" | "LEADERSHIP" | "ADMIN";
  display_name: string;
}

// ───────────────────────── Core entities ─────────────────────────

export interface Account {
  id: string; // e.g. "ACC-00042"
  legal_name: string;
  account_type_id: number; // FK -> account_type
  address: string;
  industry: string;
  website: string;
  first_contact_at: string; // date
  promoted_to_client_at: string | null; // datetime
  created_at: string; // datetime
  deleted_at: string | null; // datetime
}

export interface Contact {
  id: string; // uuid
  account_id: string; // FK -> account
  contact_type_id: number; // FK -> contact_type
  full_name: string;
  email: string;
  phone: string;
  title: string;
  is_primary: boolean;
  is_distribution_list: boolean;
}

/** Exactly one of employee_id / team_id is set. */
export interface AccountAssignment {
  id: string; // uuid
  account_id: string; // FK -> account
  employee_id: string | null; // FK -> employee, one of employee/team
  team_id: number | null; // FK -> team, one of employee/team
  role_id: number; // FK -> role
  assigned_from: string; // date
  assigned_until: string | null; // date
}

export interface Agreement {
  id: string; // e.g. "AGR-2026-NDA-00042"
  account_id: string; // FK -> account
  agreement_type_id: number; // FK -> agreement_type
  agreement_status_id: number; // FK -> agreement_status
  title: string;
  initiated_by: string;
  effective_date: string | null; // date
  expiry_date: string | null; // date
  signed_at: string | null; // datetime
  signed_by_employee_id: string | null; // FK -> employee
  supersedes_agreement_id: string | null; // FK -> agreement
  sla_due_at: string | null; // datetime
  sla_breached_at: string | null; // datetime
  sharepoint_folder_url: string;
  notes: string;
  created_at: string; // datetime
  deleted_at: string | null; // datetime
}

export interface Project {
  id: string; // e.g. "PRJ-00017"
  account_id: string; // FK -> account
  opportunity_id: string | null; // FK -> opportunity, nullable
  name: string;
  description: string;
  project_status_id: number; // FK -> project_status
  account_executive_employee_id: string; // FK -> employee
  start_date: string; // date
  target_end_date: string | null; // date
  actual_end_date: string | null; // date
  created_at: string; // datetime
  deleted_at: string | null; // datetime
}

export interface Communication {
  id: string; // uuid
  agreement_id: string | null; // FK -> agreement, nullable
  received_via_team_id: number | null; // FK -> team, nullable
  direction: "Inbound" | "Outbound" | "Meeting";
  channel: string;
  subject: string;
  from_address: string;
  to_recipients: string;
  cc_recipients: string;
  graph_message_id: string;
  occurred_at: string; // datetime
  source: string;
  logged_by_employee_id: string; // FK -> employee
}

export interface Opportunity {
  id: string; // e.g. "OPP-00031"
  account_id: string; // FK -> account
  name: string;
  opportunity_stage_id: number; // FK -> opportunity_stage
  estimated_value: number; // decimal
  currency: string;
  expected_close_date: string; // date
  owner_employee_id: string; // FK -> employee
  lost_reason: string;
  created_at: string; // datetime
  updated_at: string; // datetime
  deleted_at: string | null; // datetime
}

export interface OpportunityDocument {
  id: string; // uuid
  opportunity_id: string; // FK -> opportunity
  version_number: number;
  doc_type: "PROPOSAL" | "QUOTE";
  status: "DRAFT" | "SENT" | "ACCEPTED" | "REJECTED";
  sharepoint_item_id: string;
  sharepoint_url: string;
}

export interface SowDetail {
  agreement_id: string; // PK + FK -> agreement
  project_id: string; // FK -> project, NOT NULL
  governing_msa_id: string; // FK -> agreement, NOT NULL
  billing_model: "T_AND_M" | "FIXED" | "HYBRID";
  total_value: number; // decimal
  currency: string;
  headcount: number;
  invoicing_frequency: "MONTHLY" | "MILESTONE" | "CUSTOM";
}

export interface Employee {
  id: string; // uuid
  entra_object_id: string;
  email: string;
  full_name: string;
  is_active: boolean;
}

export interface EmployeeRole {
  employee_id: string; // PK + FK -> employee
  role_id: number; // PK + FK -> role
}

/** Exactly one of employee_id / external_name is set. */
export interface SowTeamMember {
  id: string; // uuid
  agreement_id: string; // FK -> agreement
  employee_id: string | null; // FK -> employee, internal; one of employee/external
  external_name: string | null; // external; one of employee/external
  rate_card_id: string; // FK -> sow_rate_card, role fallback rate
  override_rate_per_hour: number | null; // decimal, person-specific override
  assigned_from: string; // date
  assigned_until: string | null; // date
}

export interface SowTimesheet {
  id: string; // uuid
  sow_team_member_id: string; // FK -> sow_team_member
  agreement_id: string; // FK -> agreement
  week_start_date: string; // date, must be a Monday
  hours: number; // decimal
  status: "SUBMITTED" | "APPROVED" | "REJECTED";
  submitted_by_employee_id: string; // FK -> employee
  approved_by_employee_id: string | null; // FK -> employee
  approved_at: string | null; // datetime
  notes: string;
  created_at: string; // datetime
}

export interface Team {
  id: number;
  address: string;
  display_name: string;
  purpose: "SALES" | "NDA_REVIEW" | "AE" | "LEADERSHIP" | "GENERAL";
  is_active: boolean;
  created_at: string; // datetime
}

export interface AgreementDocument {
  id: string; // uuid
  agreement_id: string; // FK -> agreement
  version_number: number;
  filename: string;
  sharepoint_item_id: string;
  sharepoint_url: string;
  content_type: string;
  size_bytes: number; // bigint
  uploaded_by_source: "USER" | "EMAIL" | "SYSTEM";
  uploaded_at: string; // datetime
}

export interface AgreementClause {
  id: string; // uuid
  agreement_id: string; // FK -> agreement
  section_ref: string;
  clause_text: string;
  is_flagged: boolean;
  flag_reason: string;
  policy_ref: string;
  resolution_status: "OPEN" | "AMENDED" | "ACCEPTED" | "WAIVED";
}

export interface AgreementReview {
  id: string; // uuid
  agreement_id: string; // FK -> agreement
  reviewer_type: "HUMAN" | "AGENT";
  reviewer_employee_id: string | null; // FK -> employee
  summary: string;
  outcome: "APPROVED" | "NEEDS_AMENDMENT" | "REJECTED";
  reviewed_at: string; // datetime
}

export interface SowMilestone {
  id: string; // uuid
  agreement_id: string; // FK -> agreement
  milestone_name: string;
  planned_date: string; // date
  actual_date: string | null; // date
  amount: number; // decimal
  status: "UPCOMING" | "DELIVERED" | "INVOICED" | "PAID" | "DELAYED";
  invoiced_at: string | null; // datetime
  invoice_ref: string;
  notes: string;
}

export interface Notification {
  id: string; // uuid
  agreement_id: string | null; // FK -> agreement
  account_id: string | null; // FK -> account
  notification_type:
    | "SLA_REMINDER"
    | "SLA_BREACH"
    | "BUDGET_THRESHOLD"
    | "MILESTONE_APPROACHING"
    | "EXPIRY_WARNING";
  severity: "INFO" | "WARN" | "CRITICAL";
  sent_at: string; // datetime
  acknowledged: boolean;
}

/** History table: revising a budget inserts a new row and flips the old one's is_current to false. */
export interface SowBudget {
  id: string; // uuid
  agreement_id: string; // FK -> agreement
  amount: number; // decimal
  currency: string;
  alert_threshold_percents: string; // e.g. "70,80"
  effective_from: string; // date
  is_current: boolean;
  reason: string;
  created_at: string; // datetime
}

export interface SowRateCard {
  id: string; // uuid
  agreement_id: string; // FK -> agreement
  role_label: string; // e.g. "Senior Engineer"
  rate_per_hour: number; // decimal
  currency: string;
  effective_from: string; // date
  notes: string;
}

export interface AuditLog {
  id: string; // uuid
  entity_type: string;
  entity_id: string;
  action: string;
  field_changed: string;
  old_value: string;
  new_value: string;
  performed_by_employee_id: string; // FK -> employee
  performed_at: string; // datetime
}
