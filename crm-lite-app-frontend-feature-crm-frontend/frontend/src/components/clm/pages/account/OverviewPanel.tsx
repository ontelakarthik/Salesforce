"use client";

import { useEffect, useState, useTransition } from "react";
import RoleOnly from "../../RoleOnly";
import Badge from "../../Badge";
import { CountrySelect, StateProvinceSelect } from "../../CountryStateFields";
import { ApiError, useApi } from "@/lib/api/client";
import { updateAccount, type AccountOut, type AccountUpdatePayload } from "@/lib/api/crm";
import { useFieldPermissions } from "@/lib/api/fieldPermissions";
import { ACCOUNT_TYPE_BADGE, ACCOUNT_TYPE_LABEL, URL_RE, type AccountType } from "./mock";

function typeBadge(code: string) {
  return ACCOUNT_TYPE_BADGE[code as AccountType] ?? "gray";
}

function typeLabel(code: string) {
  return ACCOUNT_TYPE_LABEL[code as AccountType] ?? code;
}

/** AccountOut's date fields are full ISO datetimes (unlike mock.ts's plain-date formatDate). */
function formatDate(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

const OWNERSHIPS = ["", "PUBLIC", "PRIVATE", "SUBSIDIARY", "OTHER"];
const RATINGS = ["", "HOT", "WARM", "COLD"];

interface Draft {
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

function toDraft(account: AccountOut): Draft {
  return {
    legal_name: account.legal_name ?? "",
    account_site: account.account_site ?? "",
    industry: account.industry ?? "",
    website: account.website ?? "",
    phone: account.phone ?? "",
    address: account.address ?? "",
    billing_country: account.billing_country ?? "",
    billing_state_province: account.billing_state_province ?? "",
    shipping_address: account.shipping_address ?? "",
    shipping_country: account.shipping_country ?? "",
    shipping_state_province: account.shipping_state_province ?? "",
    annual_revenue: account.annual_revenue != null ? String(account.annual_revenue) : "",
    num_employees: account.num_employees != null ? String(account.num_employees) : "",
    ownership: account.ownership ?? "",
    ticker_symbol: account.ticker_symbol ?? "",
    rating: account.rating ?? "",
    account_number: account.account_number ?? "",
    sic_code: account.sic_code ?? "",
    description: account.description ?? "",
  };
}

function validate(d: Draft): Record<string, string> {
  const e: Record<string, string> = {};
  if (!d.legal_name.trim()) e.legal_name = "Legal name is required.";
  else if (d.legal_name.length > 200) e.legal_name = "Must be 200 characters or fewer.";
  if (d.industry.length > 100) e.industry = "Must be 100 characters or fewer.";
  if (d.website.trim() && !URL_RE.test(d.website.trim())) e.website = "Enter a valid URL.";
  if (d.address.length > 300) e.address = "Must be 300 characters or fewer.";
  return e;
}

export default function OverviewPanel({
  accountId,
  initialAccount,
  editing,
  onEditingChange,
}: {
  accountId: string;
  initialAccount: AccountOut;
  editing: boolean;
  onEditingChange: (v: boolean) => void;
}) {
  const api = useApi();
  const { isVisible, isEditable } = useFieldPermissions("ACCOUNT");
  const [account, setAccount] = useState(initialAccount);
  const [draft, setDraft] = useState<Draft>(toDraft(initialAccount));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    setAccount(initialAccount);
  }, [initialAccount]);

  function startEdit() {
    setDraft(toDraft(account));
    setErrors({});
    onEditingChange(true);
  }

  function save() {
    const e = validate(draft);
    setErrors(e);
    if (Object.keys(e).length > 0) return;

    startTransition(async () => {
      try {
        const payload: AccountUpdatePayload = {
          legal_name: draft.legal_name,
          account_site: draft.account_site || null,
          industry: draft.industry || null,
          website: draft.website || null,
          phone: draft.phone || null,
          address: draft.address || null,
          billing_country: draft.billing_country || null,
          billing_state_province: draft.billing_state_province || null,
          shipping_address: draft.shipping_address || null,
          shipping_country: draft.shipping_country || null,
          shipping_state_province: draft.shipping_state_province || null,
          annual_revenue: draft.annual_revenue.trim() ? Number(draft.annual_revenue) : null,
          num_employees: draft.num_employees.trim() ? Number(draft.num_employees) : null,
          ownership: draft.ownership || null,
          ticker_symbol: draft.ticker_symbol || null,
          rating: draft.rating || null,
          account_number: draft.account_number || null,
          sic_code: draft.sic_code || null,
          description: draft.description || null,
        };
        const updated = await updateAccount(api, accountId, payload);
        setAccount(updated);
        onEditingChange(false);
      } catch (err) {
        if (err instanceof ApiError && err.fields) {
          const fieldErrors: Record<string, string> = {};
          for (const f of err.fields) {
            const key = String(f.loc[f.loc.length - 1]);
            fieldErrors[key] = f.msg;
          }
          setErrors(fieldErrors);
        } else {
          setErrors({ legal_name: err instanceof ApiError ? err.message : "Failed to save changes." });
        }
      }
    });
  }

  if (!editing) {
    return (
      <div className="card card-pad">
        <div className="fields">
          {isVisible("legal_name") && (
            <div className="field"><div className="lab">Legal name <span className="req">*</span></div><div className="val">{account.legal_name}</div></div>
          )}
          <div className="field"><div className="lab">Account type</div><div className="val"><Badge variant={typeBadge(account.account_type)}>{typeLabel(account.account_type)}</Badge></div></div>
          {isVisible("account_site") && (
            <div className="field"><div className="lab">Account site</div><div className="val">{account.account_site || "—"}</div></div>
          )}
          {isVisible("industry") && (
            <div className="field"><div className="lab">Industry</div><div className="val">{account.industry || "—"}</div></div>
          )}
          {isVisible("website") && (
            <div className="field"><div className="lab">Website</div><div className="val">{account.website || "—"}</div></div>
          )}
          {isVisible("phone") && (
            <div className="field"><div className="lab">Phone</div><div className="val">{account.phone || "—"}</div></div>
          )}
          {isVisible("ownership") && (
            <div className="field"><div className="lab">Ownership</div><div className="val">{account.ownership || "—"}</div></div>
          )}
          {isVisible("rating") && (
            <div className="field"><div className="lab">Rating</div><div className="val">{account.rating || "—"}</div></div>
          )}
          {isVisible("ticker_symbol") && (
            <div className="field"><div className="lab">Ticker symbol</div><div className="val">{account.ticker_symbol || "—"}</div></div>
          )}
          {isVisible("annual_revenue") && (
            <div className="field"><div className="lab">Annual revenue</div><div className="val num">{account.annual_revenue != null ? account.annual_revenue.toLocaleString() : "—"}</div></div>
          )}
          {isVisible("num_employees") && (
            <div className="field"><div className="lab">No. of employees</div><div className="val num">{account.num_employees ?? "—"}</div></div>
          )}
          {isVisible("account_number") && (
            <div className="field"><div className="lab">Account number</div><div className="val">{account.account_number || "—"}</div></div>
          )}
          {isVisible("sic_code") && (
            <div className="field"><div className="lab">SIC code</div><div className="val">{account.sic_code || "—"}</div></div>
          )}
          {isVisible("billing_country") && (
            <div className="field"><div className="lab">Billing country</div><div className="val">{account.billing_country || "—"}</div></div>
          )}
          {isVisible("billing_state_province") && (
            <div className="field"><div className="lab">Billing state/province</div><div className="val">{account.billing_state_province || "—"}</div></div>
          )}
          {/* Region is always derived server-side from Billing Country +
              Billing State/Province (never user-entered) — shown read-only
              whenever an account has one, same as Lead's Region field. */}
          <div className="field"><div className="lab">Region</div><div className="val">{account.region || "—"}</div></div>
          {/* Sales Territory — a business access-control concept, deliberately
              separate from Billing Country/State + the derived Region above.
              Server-defaulted from the owner's employee territory at create
              time (see backend crm_service.create_account()); read-only here,
              same treatment as Region. */}
          <div className="field"><div className="lab">Sales territory</div><div className="val">{account.territory || "—"}</div></div>
          {isVisible("address") && (
            <div className="field"><div className="lab">Billing address</div><div className="val">{account.address || "—"}</div></div>
          )}
          {isVisible("shipping_country") && (
            <div className="field"><div className="lab">Shipping country</div><div className="val">{account.shipping_country || "—"}</div></div>
          )}
          {isVisible("shipping_state_province") && (
            <div className="field"><div className="lab">Shipping state/province</div><div className="val">{account.shipping_state_province || "—"}</div></div>
          )}
          {isVisible("shipping_address") && (
            <div className="field"><div className="lab">Shipping address</div><div className="val">{account.shipping_address || "—"}</div></div>
          )}
          {isVisible("description") && (
            <div className="field"><div className="lab">Description</div><div className="val">{account.description || "—"}</div></div>
          )}
          <div className="field"><div className="lab">First contact</div><div className="val">{formatDate(account.first_contact_at)}</div></div>
          {account.promoted_to_client_at && (
            <div className="field"><div className="lab">Promoted to client</div><div className="val">{formatDate(account.promoted_to_client_at)}</div></div>
          )}
        </div>
        {account.can_edit && (
          <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
            <button className="btn sm" style={{ marginTop: 18 }} onClick={startEdit}>Edit overview</button>
          </RoleOnly>
        )}
      </div>
    );
  }

  return (
    <div className="card card-pad">
      <div className="fields">
        {isVisible("legal_name") && (
          <div className="field">
            <div className="lab">Legal name <span className="req">*</span></div>
            <input className="inp" disabled={!isEditable("legal_name")} value={draft.legal_name} onChange={(e) => setDraft({ ...draft, legal_name: e.target.value })} />
            {errors.legal_name && <div className="help err">{errors.legal_name}</div>}
          </div>
        )}
        <div className="field">
          <div className="lab">Account type</div>
          <div className="val"><Badge variant={typeBadge(account.account_type)}>{typeLabel(account.account_type)}</Badge></div>
          <div className="help">Changed only via the &quot;Promote to client&quot; action, not this form.</div>
        </div>
        {isVisible("account_site") && (
          <div className="field">
            <div className="lab">Account site</div>
            <input className="inp" disabled={!isEditable("account_site")} value={draft.account_site} onChange={(e) => setDraft({ ...draft, account_site: e.target.value })} />
          </div>
        )}
        {isVisible("industry") && (
          <div className="field">
            <div className="lab">Industry</div>
            <input className="inp" disabled={!isEditable("industry")} value={draft.industry} onChange={(e) => setDraft({ ...draft, industry: e.target.value })} />
            {errors.industry && <div className="help err">{errors.industry}</div>}
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
              {OWNERSHIPS.map((o) => <option key={o} value={o}>{o || "—"}</option>)}
            </select>
          </div>
        )}
        {isVisible("rating") && (
          <div className="field">
            <div className="lab">Rating</div>
            <select className="inp" disabled={!isEditable("rating")} value={draft.rating} onChange={(e) => setDraft({ ...draft, rating: e.target.value })}>
              {RATINGS.map((r) => <option key={r} value={r}>{r || "—"}</option>)}
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
            <input className="inp" type="number" disabled={!isEditable("num_employees")} value={draft.num_employees} onChange={(e) => setDraft({ ...draft, num_employees: e.target.value })} />
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
          <div className="field">
            <div className="lab">Billing address</div>
            <textarea className="inp" disabled={!isEditable("address")} value={draft.address} onChange={(e) => setDraft({ ...draft, address: e.target.value })} />
            {errors.address && <div className="help err">{errors.address}</div>}
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
          <div className="field">
            <div className="lab">Shipping address</div>
            <textarea className="inp" disabled={!isEditable("shipping_address")} value={draft.shipping_address} onChange={(e) => setDraft({ ...draft, shipping_address: e.target.value })} />
          </div>
        )}
        {isVisible("description") && (
          <div className="field">
            <div className="lab">Description</div>
            <textarea className="inp" rows={3} disabled={!isEditable("description")} value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
          </div>
        )}
        <div className="field"><div className="lab">First contact</div><div className="val">{formatDate(account.first_contact_at)}</div></div>
      </div>
      <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
        <button className="btn primary sm" onClick={save} disabled={isPending}>
          {isPending ? "Saving…" : "Save"}
        </button>
        <button className="btn sm" onClick={() => onEditingChange(false)} disabled={isPending}>Cancel</button>
      </div>
    </div>
  );
}
