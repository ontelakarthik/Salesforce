import type {
  AgreementStatusLookup,
  AgreementTypeLookup,
  ContactTypeLookup,
  AccountTypeLookup,
  OpportunityStageLookup,
  ProjectStatusLookup,
  RoleLookup,
} from "@/types/schema";

export const ACCOUNT_TYPES: AccountTypeLookup[] = [
  { id: 1, code: "PROSPECT", display_name: "Prospect" },
  { id: 2, code: "CLIENT", display_name: "Client" },
  { id: 3, code: "PARTNER", display_name: "Partner" },
  { id: 4, code: "VENDOR", display_name: "Vendor" },
];

export const AGREEMENT_TYPES: AgreementTypeLookup[] = [
  { id: 1, code: "NDA", display_name: "Non-Disclosure Agreement", default_sla_hours: 48 },
  { id: 2, code: "MSA", display_name: "Master Service Agreement", default_sla_hours: 168 },
  { id: 3, code: "SOW", display_name: "Statement of Work", default_sla_hours: 168 },
  { id: 4, code: "RESELLER", display_name: "Reseller Agreement", default_sla_hours: 168 },
];

export const AGREEMENT_STATUSES: AgreementStatusLookup[] = [
  { id: 1, code: "DRAFT", display_name: "Draft", is_terminal: false },
  { id: 2, code: "REQUESTED", display_name: "Requested", is_terminal: false },
  { id: 3, code: "UNDER_REVIEW", display_name: "Under review", is_terminal: false },
  { id: 4, code: "SENT_FOR_SIGNATURE", display_name: "Sent for signature", is_terminal: false },
  { id: 5, code: "SIGNED", display_name: "Signed", is_terminal: false },
  { id: 6, code: "ACTIVE", display_name: "Active", is_terminal: false },
  { id: 7, code: "EXPIRING_SOON", display_name: "Expiring soon", is_terminal: false },
  { id: 8, code: "SUPERSEDED", display_name: "Superseded", is_terminal: true },
  { id: 9, code: "TERMINATED", display_name: "Terminated", is_terminal: true },
  { id: 10, code: "EXPIRED", display_name: "Expired", is_terminal: true },
];

export const PROJECT_STATUSES: ProjectStatusLookup[] = [
  { id: 1, code: "PLANNING", display_name: "Planning", is_terminal: false },
  { id: 2, code: "ACTIVE", display_name: "Active", is_terminal: false },
  { id: 3, code: "ON_HOLD", display_name: "On hold", is_terminal: false },
  { id: 4, code: "COMPLETED", display_name: "Completed", is_terminal: true },
];

export const OPPORTUNITY_STAGES: OpportunityStageLookup[] = [
  { id: 1, code: "NEW", display_name: "New", is_terminal: false },
  { id: 2, code: "QUALIFIED", display_name: "Qualified", is_terminal: false },
  { id: 3, code: "PROPOSAL", display_name: "Proposal", is_terminal: false },
  { id: 4, code: "NEGOTIATION", display_name: "Negotiation", is_terminal: false },
  { id: 5, code: "WON", display_name: "Won", is_terminal: true },
  { id: 6, code: "LOST", display_name: "Lost", is_terminal: true },
];

export const CONTACT_TYPES: ContactTypeLookup[] = [
  { id: 1, code: "BUSINESS", display_name: "Business" },
  { id: 2, code: "LEGAL", display_name: "Legal" },
  { id: 3, code: "PROCUREMENT", display_name: "Procurement" },
  { id: 4, code: "FINANCE", display_name: "Finance" },
  { id: 5, code: "TECHNICAL", display_name: "Technical" },
];

export const ROLES: RoleLookup[] = [
  { id: 1, code: "SALES", display_name: "Sales / Pre-Sales" },
  { id: 2, code: "ACCOUNT_EXEC", display_name: "Account Executive" },
  { id: 3, code: "LEADERSHIP", display_name: "Leadership" },
  { id: 4, code: "ADMIN", display_name: "Administrator" },
];

export function lookupById<T extends { id: number }>(rows: T[], id: number): T | undefined {
  return rows.find((r) => r.id === id);
}
