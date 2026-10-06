"use client";

/**
 * Industry and No. of employees picklists, shared by the New Lead form (both
 * "Select Existing Account" and "Create New Account" modes), the Account
 * form fields, and the Lead/Account detail pages.
 *
 * Backend representation (unchanged): `industry` is a free string and
 * `num_employees` is an integer on both Lead and Account. So the employee
 * range picklist maps each range to one representative integer on save, and
 * bucketFor() maps any stored integer (including legacy values entered
 * before the picklist existed) back to its range for display.
 */

export const INDUSTRIES = [
  "Agriculture", "Apparel", "Banking", "Biotechnology", "Chemicals", "Communications",
  "Construction", "Consulting", "Education", "Electronics", "Energy", "Engineering",
  "Entertainment", "Environmental", "Finance", "Food & Beverage", "Government", "Healthcare",
  "Hospitality", "Insurance", "Machinery", "Manufacturing", "Media", "Not For Profit",
  "Other", "Recreation", "Retail", "Shipping", "Technology", "Telecommunications",
  "Transportation", "Utilities",
] as const;

interface EmployeeRange {
  label: string;
  /** Integer persisted to `num_employees` when this range is picked. */
  value: number;
  /** Whether a stored integer belongs to this range (upper bound inclusive, so
   * 500 is "100-500", 501..1000 is "500-1000", and so on). */
  contains: (n: number) => boolean;
}

export const EMPLOYEE_RANGES: EmployeeRange[] = [
  { label: "<less than 100", value: 50, contains: (n) => n < 100 },
  { label: "100-500", value: 300, contains: (n) => n >= 100 && n <= 500 },
  { label: "500-1000", value: 750, contains: (n) => n > 500 && n <= 1000 },
  { label: "1000-2000", value: 1500, contains: (n) => n > 1000 && n <= 2000 },
  { label: "2000-3000", value: 2500, contains: (n) => n > 2000 && n <= 3000 },
  { label: "3000-4000", value: 3500, contains: (n) => n > 3000 && n <= 4000 },
  { label: "4000-5000", value: 4500, contains: (n) => n > 4000 && n <= 5000 },
  { label: ">greater than 5000", value: 6000, contains: (n) => n > 5000 },
];

/** Range label for a stored employee count (number or numeric string), or
 * null if there is no usable value. */
export function employeeRangeLabel(value: number | string | null | undefined): string | null {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  return EMPLOYEE_RANGES.find((r) => r.contains(n))?.label ?? null;
}

/** Case-insensitive match of a stored industry against the picklist; returns
 * the canonical picklist value, or "" if it isn't one of the allowed values. */
export function matchIndustry(value: string | null | undefined): string {
  const v = (value ?? "").trim().toLowerCase();
  return INDUSTRIES.find((i) => i.toLowerCase() === v) ?? "";
}

export function IndustrySelect({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <select className="inp" disabled={disabled} value={matchIndustry(value)} onChange={(e) => onChange(e.target.value)}>
      <option value="">Select Industry</option>
      {INDUSTRIES.map((i) => <option key={i} value={i}>{i}</option>)}
    </select>
  );
}

/** `value`/`onChange` use the same string-of-an-integer shape the drafts
 * already use for num_employees, so the existing `Number(...)` conversion on
 * submit keeps working unchanged. */
export function EmployeeRangeSelect({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const current = EMPLOYEE_RANGES.find((r) => r.label === employeeRangeLabel(value));
  return (
    <select
      className="inp"
      disabled={disabled}
      value={current ? String(current.value) : ""}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">--None--</option>
      {EMPLOYEE_RANGES.map((r) => <option key={r.label} value={String(r.value)}>{r.label}</option>)}
    </select>
  );
}
