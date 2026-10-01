import type { Api } from "./client";

/** Wire types for the Admin module (src/models/admin_models.py). */
export interface EmployeeOut {
  id: string;
  entra_object_id: string | null;
  email: string;
  full_name: string;
  is_active: boolean;
  must_change_password: boolean;
  roles: string[];
  // Sales Territory this employee is assigned to — part of their
  // authorization/assignment data, used to default the territory of an
  // Account/Lead they create (see backend crm_service.create_account()).
  // The relationship is by id, never by Territory's (optional, nullable)
  // Code — territory_name is the resolved display name, for the UI only.
  territory_id: number | null;
  territory_name: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** POST /admin/employees's actual response — adds whether the welcome email
 * (with the system-generated temp password) actually sent. See
 * admin_service.create_employee() on the backend. */
export interface EmployeeCreateOut extends EmployeeOut {
  password_email_sent: boolean;
}

export interface EmployeeCreatePayload {
  email: string;
  full_name: string;
  territory_id?: number | null;
}

export interface EmployeeUpdatePayload {
  full_name?: string;
  is_active?: boolean;
  territory_id?: number | null;
}

export function listEmployees(api: Api): Promise<EmployeeOut[]> {
  return api.get<EmployeeOut[]>("/admin/employees");
}

export function createEmployee(api: Api, payload: EmployeeCreatePayload): Promise<EmployeeCreateOut> {
  return api.post<EmployeeCreateOut>("/admin/employees", payload);
}

export function updateEmployee(api: Api, employeeId: string, payload: EmployeeUpdatePayload): Promise<EmployeeOut> {
  return api.patch<EmployeeOut>(`/admin/employees/${employeeId}`, payload);
}

export function setEmployeeProfiles(api: Api, employeeId: string, profileCodes: string[]): Promise<EmployeeOut> {
  return api.put<EmployeeOut>(`/admin/employees/${employeeId}/profiles`, { profile_codes: profileCodes });
}

/** GET /employees/directory — a deliberately minimal projection (id +
 * full_name only) available to every authenticated role, unlike
 * listEmployees() above which is admin-only. Use this to resolve an
 * owner/signer/reviewer/approver id to a display name; see
 * lib/api/identity.ts's useEmployeeDirectory() for the cached hook most
 * components should actually use instead of calling this directly. */
export interface EmployeeDirectoryEntry {
  id: string;
  full_name: string;
}

export function listEmployeeDirectory(api: Api): Promise<EmployeeDirectoryEntry[]> {
  return api.get<EmployeeDirectoryEntry[]>("/employees/directory");
}

export interface TeamOut {
  id: number;
  display_name: string;
  purpose: string | null;
  address: string | null;
  is_active: boolean;
}

export interface TeamCreatePayload {
  display_name: string;
  purpose?: string | null;
  address?: string | null;
}

export interface TeamUpdatePayload {
  display_name?: string;
  purpose?: string | null;
  address?: string | null;
  is_active?: boolean;
}

export function listTeams(api: Api): Promise<TeamOut[]> {
  return api.get<TeamOut[]>("/admin/teams");
}

export function createTeam(api: Api, payload: TeamCreatePayload): Promise<TeamOut> {
  return api.post<TeamOut>("/admin/teams", payload);
}

export function updateTeam(api: Api, teamId: number, payload: TeamUpdatePayload): Promise<TeamOut> {
  return api.patch<TeamOut>(`/admin/teams/${teamId}`, payload);
}

/** Valid values for `table` per admin_service._LOOKUP_TABLES. "role" is
 * deliberately not here — Profiles (lib/api/profiles.ts) have their own
 * dedicated CRUD now instead of the generic lookup path. */
export type LookupTable =
  | "account_type"
  | "contact_type"
  | "opportunity_stage"
  | "agreement_type"
  | "agreement_status"
  | "project_status"
  | "call_disposition"
  | "territory";

export interface LookupOut {
  id: number;
  // Optional only for territory — every other lookup table's code is still
  // always present (see backend admin_models.LookupCreate's docstring).
  code: string | null;
  display_name: string;
  is_terminal: boolean | null;
  default_sla_hours: number | null;
  is_active: boolean | null; // territory only
  description: string | null; // territory only
  country: string | null; // territory only
  region: string | null; // territory only
  parent_territory_id: number | null; // territory only
}

export interface LookupCreatePayload {
  // Optional only for territory — required (enforced server-side) for
  // every other table.
  code?: string;
  display_name: string;
  is_terminal?: boolean | null;
  default_sla_hours?: number | null;
  is_active?: boolean | null; // territory only
  description?: string | null; // territory only
  country?: string | null; // territory only, required for territory
  region?: string | null; // territory only, optional (a top-level/
                          // country-wide territory has no single region)
  parent_territory_id?: number | null; // territory only, optional
}

export interface LookupUpdatePayload {
  display_name?: string;
  is_terminal?: boolean | null;
  default_sla_hours?: number | null;
  is_active?: boolean | null; // territory only
  description?: string | null; // territory only
  country?: string | null; // territory only
  region?: string | null; // territory only, optional
  parent_territory_id?: number | null; // territory only, optional
}

export function listLookups(api: Api, table: LookupTable): Promise<LookupOut[]> {
  return api.get<LookupOut[]>(`/admin/lookups/${table}`);
}

export function addLookup(api: Api, table: LookupTable, payload: LookupCreatePayload): Promise<LookupOut> {
  return api.post<LookupOut>(`/admin/lookups/${table}`, payload);
}

export function updateLookup(
  api: Api,
  table: LookupTable,
  lookupId: number,
  payload: LookupUpdatePayload
): Promise<LookupOut> {
  return api.patch<LookupOut>(`/admin/lookups/${table}/${lookupId}`, payload);
}
