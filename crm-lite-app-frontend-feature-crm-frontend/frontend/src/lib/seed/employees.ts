import type { Employee, EmployeeRole, Team } from "@/types/schema";

export const EMPLOYEES: Employee[] = [
  { id: "emp-monish", entra_object_id: "entra-monish", email: "monish.rao@tachyon.com", full_name: "Monish Rao", is_active: true },
  { id: "emp-deepthi", entra_object_id: "entra-deepthi", email: "deepthi.t@tachyon.com", full_name: "Deepthi T.", is_active: true },
  { id: "emp-aasritha", entra_object_id: "entra-aasritha", email: "aasritha.k@tachyon.com", full_name: "Aasritha K.", is_active: true },
  { id: "emp-venkat", entra_object_id: "entra-venkat", email: "venkat.n@tachyon.com", full_name: "Venkat N.", is_active: true },
  { id: "emp-rajesh", entra_object_id: "entra-rajesh", email: "rajesh.s@tachyon.com", full_name: "Rajesh S.", is_active: true },
  { id: "emp-uday", entra_object_id: "entra-uday", email: "uday.d@tachyon.com", full_name: "Uday D.", is_active: true },
  { id: "emp-shivam", entra_object_id: "entra-shivam", email: "shivam.c@tachyon.com", full_name: "Shivam C.", is_active: true },
  { id: "emp-yethishwar", entra_object_id: "entra-yethishwar", email: "yethishwar@tachyon.com", full_name: "Yethishwar", is_active: true },
];

export const EMPLOYEE_ROLES: EmployeeRole[] = [
  { employee_id: "emp-monish", role_id: 2 }, // ACCOUNT_EXEC
  { employee_id: "emp-deepthi", role_id: 2 }, // ACCOUNT_EXEC
  { employee_id: "emp-deepthi", role_id: 4 }, // ADMIN
  { employee_id: "emp-aasritha", role_id: 1 }, // SALES
  { employee_id: "emp-venkat", role_id: 3 }, // LEADERSHIP
];

export const TEAMS: Team[] = [
  { id: 1, address: "deals@tachyon.com", display_name: "Sales & Pre-Sales", purpose: "SALES", is_active: true, created_at: "2025-01-01T00:00:00Z" },
  { id: 2, address: "nda@tachyon.com", display_name: "NDA Review", purpose: "NDA_REVIEW", is_active: true, created_at: "2025-01-01T00:00:00Z" },
  { id: 3, address: "accounts@tachyon.com", display_name: "Account Executives", purpose: "AE", is_active: true, created_at: "2025-01-01T00:00:00Z" },
];

export function employeeById(id: string | null): Employee | undefined {
  return id ? EMPLOYEES.find((e) => e.id === id) : undefined;
}

export function employeeName(id: string | null): string {
  return employeeById(id)?.full_name ?? "—";
}
