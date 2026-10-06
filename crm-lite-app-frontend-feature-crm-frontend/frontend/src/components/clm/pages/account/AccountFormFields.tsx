"use client";

import { CountrySelect, StateProvinceSelect } from "../../CountryStateFields";
import { URL_RE } from "./mock";
import { EmployeeRangeSelect, IndustrySelect } from "../picklists";
import type { AccountCreatePayload } from "@/lib/api/crm";

/**
 * Account draft shape + field-rendering, shared between the standalone
 * NewAccountModal and the inline "Create New Account" option on the New
 * Lead flow (see NewLeadModal.tsx) — one definition of the Account form so
 * the two never drift apart.
 */
export interface AccountDraft {
  legal_name: string;
  account_site: string;
  industry: string;
  website: string;
  phone: string;
  address: string;
  billing_country: string;
  billing_state_province: string;
  shipping_address: string;
  shipping_country: string;
  shipping_state_province: string;
  annual_revenue: string;
  num_employees: string;
  ownership: string;
  ticker_symbol: string;
  rating: string;
  account_number: string;
  sic_code: string;
  description: string;
}

export const BLANK_ACCOUNT_DRAFT: AccountDraft = {
  legal_name: "",
  account_site: "",
  industry: "",
  website: "",
  phone: "",
  address: "",
  billing_country: "",
  billing_state_province: "",
  shipping_address: "",
  shipping_country: "",
  shipping_state_province: "",
  annual_revenue: "",
  num_employees: "",
  ownership: "",
  ticker_symbol: "",
  rating: "",
  account_number: "",
  sic_code: "",
  description: "",
};

export const ACCOUNT_OWNERSHIPS = ["", "PUBLIC", "PRIVATE", "SUBSIDIARY", "OTHER"];
export const ACCOUNT_RATINGS = ["", "HOT", "WARM", "COLD"];

export function validateAccountDraft(d: AccountDraft): Record<string, string> {
  const e: Record<string, string> = {};
  if (!d.legal_name.trim()) e.legal_name = "Legal name is required.";
  else if (d.legal_name.trim().length < 2) e.legal_name = "Must be at least 2 characters.";
  if (d.website.trim() && !URL_RE.test(d.website.trim())) e.website = "Enter a valid URL.";
  return e;
}

export function accountDraftToPayload(d: AccountDraft): AccountCreatePayload {
  return {
    legal_name: d.legal_name.trim(),
    account_site: d.account_site.trim() || null,
    industry: d.industry.trim() || null,
    website: d.website.trim() || null,
    phone: d.phone.trim() || null,
    address: d.address.trim() || null,
    billing_country: d.billing_country || null,
    billing_state_province: d.billing_state_province || null,
    shipping_address: d.shipping_address.trim() || null,
    shipping_country: d.shipping_country || null,
    shipping_state_province: d.shipping_state_province || null,
    annual_revenue: d.annual_revenue.trim() ? Number(d.annual_revenue) : null,
    num_employees: d.num_employees.trim() ? Number(d.num_employees) : null,
    ownership: d.ownership || null,
    ticker_symbol: d.ticker_symbol.trim() || null,
    rating: d.rating || null,
    account_number: d.account_number.trim() || null,
    sic_code: d.sic_code.trim() || null,
    description: d.description.trim() || null,
  };
}

export function AccountFormFields({
  draft,
  setDraft,
  errors,
  isVisible,
  isEditable,
  autoFocusLegalName = false,
}: {
  draft: AccountDraft;
  setDraft: (d: AccountDraft) => void;
  errors: Record<string, string>;
  isVisible: (field: string) => boolean;
  isEditable: (field: string) => boolean;
  autoFocusLegalName?: boolean;
}) {
  return (
    <>
      <div className="field" style={{ gridColumn: "1 / -1" }}>
        <div className="lab">Legal name <span className="req">*</span></div>
        <input className="inp" value={draft.legal_name} onChange={(e) => setDraft({ ...draft, legal_name: e.target.value })} autoFocus={autoFocusLegalName} />
        {errors.legal_name && <div className="help err">{errors.legal_name}</div>}
      </div>
      {isVisible("account_site") && (
        <div className="field">
          <div className="lab">Account site</div>
          <input className="inp" disabled={!isEditable("account_site")} placeholder="e.g. Headquarters" value={draft.account_site} onChange={(e) => setDraft({ ...draft, account_site: e.target.value })} />
        </div>
      )}
      {isVisible("industry") && (
        <div className="field">
          <div className="lab">Industry</div>
          <IndustrySelect disabled={!isEditable("industry")} value={draft.industry} onChange={(industry) => setDraft({ ...draft, industry })} />
        </div>
      )}
      {isVisible("website") && (
        <div className="field">
          <div className="lab">Website</div>
          <input className="inp" disabled={!isEditable("website")} value={draft.website} onChange={(e) => setDraft({ ...draft, website: e.target.value })} />
          {errors.website && <div className="help err">{errors.website}</div>}
        </div>
      )}
      {isVisible("phone") && (
        <div className="field">
          <div className="lab">Phone</div>
          <input className="inp" disabled={!isEditable("phone")} value={draft.phone} onChange={(e) => setDraft({ ...draft, phone: e.target.value })} />
        </div>
      )}
      {isVisible("ownership") && (
        <div className="field">
          <div className="lab">Ownership</div>
          <select className="inp" disabled={!isEditable("ownership")} value={draft.ownership} onChange={(e) => setDraft({ ...draft, ownership: e.target.value })}>
            {ACCOUNT_OWNERSHIPS.map((o) => <option key={o} value={o}>{o || "—"}</option>)}
          </select>
        </div>
      )}
      {isVisible("rating") && (
        <div className="field">
          <div className="lab">Rating</div>
          <select className="inp" disabled={!isEditable("rating")} value={draft.rating} onChange={(e) => setDraft({ ...draft, rating: e.target.value })}>
            {ACCOUNT_RATINGS.map((r) => <option key={r} value={r}>{r || "—"}</option>)}
          </select>
        </div>
      )}
      {isVisible("ticker_symbol") && (
        <div className="field">
          <div className="lab">Ticker symbol</div>
          <input className="inp" disabled={!isEditable("ticker_symbol")} value={draft.ticker_symbol} onChange={(e) => setDraft({ ...draft, ticker_symbol: e.target.value })} />
        </div>
      )}
      {isVisible("annual_revenue") && (
        <div className="field">
          <div className="lab">Annual revenue</div>
          <input className="inp" type="number" disabled={!isEditable("annual_revenue")} value={draft.annual_revenue} onChange={(e) => setDraft({ ...draft, annual_revenue: e.target.value })} />
        </div>
      )}
      {isVisible("num_employees") && (
        <div className="field">
          <div className="lab">No. of employees</div>
          <EmployeeRangeSelect disabled={!isEditable("num_employees")} value={draft.num_employees} onChange={(num_employees) => setDraft({ ...draft, num_employees })} />
        </div>
      )}
      {isVisible("account_number") && (
        <div className="field">
          <div className="lab">Account number</div>
          <input className="inp" disabled={!isEditable("account_number")} value={draft.account_number} onChange={(e) => setDraft({ ...draft, account_number: e.target.value })} />
        </div>
      )}
      {isVisible("sic_code") && (
        <div className="field">
          <div className="lab">SIC code</div>
          <input className="inp" disabled={!isEditable("sic_code")} value={draft.sic_code} onChange={(e) => setDraft({ ...draft, sic_code: e.target.value })} />
        </div>
      )}
      {isVisible("billing_country") && (
        <div className="field">
          <div className="lab">Billing country</div>
          <CountrySelect
            disabled={!isEditable("billing_country")}
            value={draft.billing_country}
            onChange={(billing_country) => setDraft({ ...draft, billing_country, billing_state_province: "" })}
          />
        </div>
      )}
      {isVisible("billing_state_province") && (
        <div className="field">
          <div className="lab">Billing state/province</div>
          <StateProvinceSelect
            country={draft.billing_country}
            disabled={!isEditable("billing_state_province")}
            value={draft.billing_state_province}
            onChange={(billing_state_province) => setDraft({ ...draft, billing_state_province })}
          />
        </div>
      )}
      {isVisible("address") && (
        <div className="field" style={{ gridColumn: "1 / -1" }}>
          <div className="lab">Billing address</div>
          <textarea className="inp" disabled={!isEditable("address")} value={draft.address} onChange={(e) => setDraft({ ...draft, address: e.target.value })} />
        </div>
      )}
      {isVisible("shipping_country") && (
        <div className="field">
          <div className="lab">Shipping country</div>
          <CountrySelect
            disabled={!isEditable("shipping_country")}
            value={draft.shipping_country}
            onChange={(shipping_country) => setDraft({ ...draft, shipping_country, shipping_state_province: "" })}
          />
        </div>
      )}
      {isVisible("shipping_state_province") && (
        <div className="field">
          <div className="lab">Shipping state/province</div>
          <StateProvinceSelect
            country={draft.shipping_country}
            disabled={!isEditable("shipping_state_province")}
            value={draft.shipping_state_province}
            onChange={(shipping_state_province) => setDraft({ ...draft, shipping_state_province })}
          />
        </div>
      )}
      {isVisible("shipping_address") && (
        <div className="field" style={{ gridColumn: "1 / -1" }}>
          <div className="lab">Shipping address</div>
          <textarea className="inp" disabled={!isEditable("shipping_address")} value={draft.shipping_address} onChange={(e) => setDraft({ ...draft, shipping_address: e.target.value })} />
        </div>
      )}
      {isVisible("description") && (
        <div className="field" style={{ gridColumn: "1 / -1" }}>
          <div className="lab">Description</div>
          <textarea className="inp" rows={3} disabled={!isEditable("description")} value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
        </div>
      )}
    </>
  );
}
