"use client";

import { CountrySelect, StateProvinceSelect } from "../CountryStateFields";

export interface AddressValues {
  street: string;
  city: string;
  state_province: string;
  country: string;
  postal_code: string;
}

type AddressPart = keyof AddressValues;

/**
 * Structured address block — Street, City, State/Province, Country, Postal
 * Code, in that order — shared by the Lead "Address" section and the
 * Account "Billing address" / "Shipping address" sections so the three
 * can't drift apart. Reuses the existing CountrySelect/StateProvinceSelect
 * (it never adds a second country/state field); picking a different country
 * clears the paired state/province, same as everywhere else those two are
 * used. `fields` maps each part to its field-level-security name so each
 * input still honours isVisible/isEditable individually.
 */
export function AddressSection({
  title,
  labels,
  fields,
  values,
  onChange,
  isVisible,
  isEditable,
}: {
  title: string;
  labels: Record<AddressPart, string>;
  fields: Record<AddressPart, string>;
  values: AddressValues;
  onChange: (next: AddressValues) => void;
  isVisible: (field: string) => boolean;
  isEditable: (field: string) => boolean;
}) {
  const show = (part: AddressPart) => isVisible(fields[part]);
  if (!(Object.keys(fields) as AddressPart[]).some(show)) return null;

  return (
    <div style={{ gridColumn: "1 / -1" }}>
      <div className="lab">{title}</div>
      <div
        className="fields"
        style={{
          gridTemplateColumns: "repeat(2, 1fr)",
          border: "1px solid var(--border)",
          borderRadius: 8,
          padding: 12,
          marginTop: 4,
        }}
      >
        {show("street") && (
          <div className="field" style={{ gridColumn: "1 / -1" }}>
            <div className="lab">{labels.street}</div>
            <input
              className="inp"
              disabled={!isEditable(fields.street)}
              value={values.street}
              onChange={(e) => onChange({ ...values, street: e.target.value })}
            />
          </div>
        )}
        {show("city") && (
          <div className="field" style={{ gridColumn: "1 / -1" }}>
            <div className="lab">{labels.city}</div>
            <input
              className="inp"
              disabled={!isEditable(fields.city)}
              value={values.city}
              onChange={(e) => onChange({ ...values, city: e.target.value })}
            />
          </div>
        )}
        {show("state_province") && (
          <div className="field">
            <div className="lab">{labels.state_province}</div>
            <StateProvinceSelect
              country={values.country}
              disabled={!isEditable(fields.state_province)}
              value={values.state_province}
              onChange={(state_province) => onChange({ ...values, state_province })}
            />
          </div>
        )}
        {show("country") && (
          <div className="field">
            <div className="lab">{labels.country}</div>
            <CountrySelect
              disabled={!isEditable(fields.country)}
              value={values.country}
              onChange={(country) => onChange({ ...values, country, state_province: "" })}
            />
          </div>
        )}
        {show("postal_code") && (
          <div className="field" style={{ gridColumn: "1 / -1" }}>
            <div className="lab">{labels.postal_code}</div>
            <input
              className="inp"
              disabled={!isEditable(fields.postal_code)}
              value={values.postal_code}
              onChange={(e) => onChange({ ...values, postal_code: e.target.value })}
            />
          </div>
        )}
      </div>
    </div>
  );
}
