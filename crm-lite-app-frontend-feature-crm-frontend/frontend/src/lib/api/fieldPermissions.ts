"use client";

import { useEffect, useState } from "react";
import { useApi, type Api } from "./client";

/** Field-Level Security — mirrors src/models/crm_models.py's
 * FieldPermissionEntry/EffectiveFieldPermission on the backend. See
 * crm_service.py's "Field-Level Security" section for the full design
 * (default-permissive, union-across-held-roles, ADMIN never restricted). */
export type FlsObjectName = "LEAD" | "ACCOUNT" | "OPPORTUNITY";

export interface FieldPermissionEntry {
  id?: string | null;
  role_id: number;
  object_name: FlsObjectName;
  field_name: string;
  visible: boolean;
  editable: boolean;
}

export interface EffectiveFieldPermission {
  visible: boolean;
  editable: boolean;
}

export type EffectiveFieldPermissions = Record<string, EffectiveFieldPermission>;

/** The only fields FLS can touch, per object — must match the backend's
 * crm_service._FLS_FIELDS exactly (the backend is the source of truth /
 * validates against this same set; this copy is just for building the
 * admin matrix UI without a round trip). */
export const FLS_FIELDS: Record<FlsObjectName, { field: string; label: string }[]> = {
  LEAD: [
    { field: "company_name", label: "Company" },
    { field: "salutation", label: "Salutation" },
    { field: "first_name", label: "First name" },
    { field: "last_name", label: "Last name" },
    { field: "title", label: "Title" },
    { field: "contact_email", label: "Email" },
    { field: "contact_phone", label: "Phone" },
    { field: "mobile_phone", label: "Mobile" },
    { field: "website", label: "Website" },
    { field: "linkedin_url", label: "LinkedIn" },
    { field: "industry", label: "Industry" },
    { field: "rating", label: "Rating" },
    { field: "annual_revenue", label: "Annual revenue" },
    { field: "num_employees", label: "No. of employees" },
    { field: "address", label: "Address" },
    { field: "country", label: "Country" },
    { field: "state_province", label: "State/Province" },
    { field: "description", label: "Description" },
    { field: "do_not_call", label: "Do not call" },
    { field: "email_opt_out", label: "Email opt out" },
    { field: "source", label: "Lead source" },
    { field: "campaign_id", label: "Campaign" },
    { field: "account_id", label: "Account" },
  ],
  ACCOUNT: [
    { field: "legal_name", label: "Legal name" },
    { field: "account_site", label: "Account site" },
    { field: "industry", label: "Industry" },
    { field: "website", label: "Website" },
    { field: "phone", label: "Phone" },
    { field: "address", label: "Billing address" },
    { field: "billing_country", label: "Billing country" },
    { field: "billing_state_province", label: "Billing state/province" },
    { field: "shipping_address", label: "Shipping address" },
    { field: "shipping_country", label: "Shipping country" },
    { field: "shipping_state_province", label: "Shipping state/province" },
    { field: "annual_revenue", label: "Annual revenue" },
    { field: "num_employees", label: "No. of employees" },
    { field: "ownership", label: "Ownership" },
    { field: "ticker_symbol", label: "Ticker symbol" },
    { field: "rating", label: "Rating" },
    { field: "account_number", label: "Account number" },
    { field: "sic_code", label: "SIC code" },
    { field: "description", label: "Description" },
    { field: "parent_account_id", label: "Parent account" },
  ],
  OPPORTUNITY: [
    { field: "name", label: "Deal name" },
    { field: "estimated_value", label: "Estimated value" },
    { field: "currency", label: "Currency" },
    { field: "expected_close_date", label: "Expected close" },
    { field: "lost_reason", label: "Lost reason" },
    { field: "probability_percent", label: "Probability %" },
    { field: "opportunity_type", label: "Opportunity type" },
    { field: "next_step", label: "Next step" },
    { field: "description", label: "Description" },
  ],
};

export function listFieldPermissions(api: Api, objectName: FlsObjectName): Promise<FieldPermissionEntry[]> {
  return api.get<FieldPermissionEntry[]>("/field-permissions", { object_name: objectName });
}

export function saveFieldPermissions(
  api: Api,
  objectName: FlsObjectName,
  entries: FieldPermissionEntry[]
): Promise<FieldPermissionEntry[]> {
  return api.put<FieldPermissionEntry[]>("/field-permissions", { object_name: objectName, entries });
}

export function getEffectiveFieldPermissions(
  api: Api,
  objectName: FlsObjectName
): Promise<EffectiveFieldPermissions> {
  return api.get<EffectiveFieldPermissions>("/field-permissions/effective", { object_name: objectName });
}

/** Fetches this user's effective field permissions for one object once per
 * mount. Defaults both isVisible/isEditable to `true` while loading or on a
 * fetch failure — the same fully-permissive fallback the backend itself
 * uses when nothing is configured, so a slow/failed request never hides a
 * field that should be there. */
export function useFieldPermissions(objectName: FlsObjectName) {
  const api = useApi();
  const [effective, setEffective] = useState<EffectiveFieldPermissions | null>(null);

  useEffect(() => {
    let cancelled = false;
    setEffective(null);
    getEffectiveFieldPermissions(api, objectName)
      .then((data) => {
        if (!cancelled) setEffective(data);
      })
      .catch(() => {
        /* stays null -> isVisible/isEditable fall back to fully permissive below */
      });
    return () => {
      cancelled = true;
    };
  }, [api, objectName]);

  function isVisible(field: string): boolean {
    return effective?.[field]?.visible ?? true;
  }

  function isEditable(field: string): boolean {
    return effective?.[field]?.editable ?? true;
  }

  return { isVisible, isEditable, loaded: effective !== null };
}
