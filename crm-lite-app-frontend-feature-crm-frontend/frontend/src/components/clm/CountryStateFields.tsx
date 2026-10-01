"use client";

import { COUNTRIES, getStateProvinceOptions, stateProvinceLabel } from "@/lib/geo";

/** Country dropdown — one shared source of the option list (src/lib/geo.ts)
 * so it's never duplicated per-form. Clearing the paired State/Province
 * value when the country changes is the caller's job (it owns the Draft
 * state), same as every other controlled field in these forms. */
export function CountrySelect({
  value,
  disabled,
  onChange,
}: {
  value: string;
  disabled?: boolean;
  onChange: (country: string) => void;
}) {
  return (
    <select className="inp" disabled={disabled} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">—</option>
      {COUNTRIES.map((c) => <option key={c} value={c}>{c}</option>)}
    </select>
  );
}

/** State/Province dropdown — options depend entirely on the selected
 * country (empty + disabled with none selected), and the placeholder wording
 * follows the country ("Select State" vs "Select Province/Territory"). */
export function StateProvinceSelect({
  country,
  value,
  disabled,
  onChange,
}: {
  country: string;
  value: string;
  disabled?: boolean;
  onChange: (stateProvince: string) => void;
}) {
  const options = getStateProvinceOptions(country);
  return (
    <select
      className="inp"
      disabled={disabled || !country}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">{country ? `Select ${stateProvinceLabel(country)}` : "—"}</option>
      {options.map((s) => <option key={s} value={s}>{s}</option>)}
    </select>
  );
}
