"use client";

import { useEffect, useState, useTransition } from "react";
import Modal from "../Modal";
import { ApiError, useApi } from "@/lib/api/client";
import {
  createAccount,
  createLead,
  listAccounts,
  type AccountOut,
  type CampaignOut,
  type LeadCreatePayload,
  type LeadOut,
} from "@/lib/api/crm";
import { useFieldPermissions } from "@/lib/api/fieldPermissions";
import { useAppDispatch } from "@/lib/hooks";
import { showToast } from "@/lib/features/toastSlice";
import { leadFieldsFromAccount } from "./leadShared";
import { EmployeeRangeSelect, IndustrySelect, matchIndustry } from "./picklists";
import { AddressSection } from "./AddressSection";
import {
  AccountFormFields,
  BLANK_ACCOUNT_DRAFT,
  accountDraftToPayload,
  validateAccountDraft,
  type AccountDraft,
} from "./account/AccountFormFields";

type AccountMode = "existing" | "new";

// Simple format check, mirrored on the backend (LeadCreate/LeadUpdate in
// crm_models.py) so the requirement can't be bypassed via a direct API call.
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

interface Draft {
  account_id: string;
  salutation: string;
  first_name: string;
  last_name: string;
  company_name: string;
  title: string;
  contact_email: string;
  contact_phone: string;
  mobile_phone: string;
  website: string;
  linkedin_url: string;
  industry: string;
  rating: string;
  annual_revenue: string;
  num_employees: string;
  campaign_id: string;
  source: string;
  address: string;
  country: string;
  state_province: string;
  city: string;
  postal_code: string;
  description: string;
  do_not_call: boolean;
  email_opt_out: boolean;
}

const BLANK: Draft = {
  account_id: "",
  salutation: "",
  first_name: "",
  last_name: "",
  company_name: "",
  title: "",
  contact_email: "",
  contact_phone: "",
  mobile_phone: "",
  website: "",
  linkedin_url: "",
  industry: "",
  rating: "",
  annual_revenue: "",
  num_employees: "",
  campaign_id: "",
  source: "",
  address: "",
  country: "",
  state_province: "",
  city: "",
  postal_code: "",
  description: "",
  do_not_call: false,
  email_opt_out: false,
};

const SALUTATIONS = ["", "Mr.", "Ms.", "Mrs.", "Dr.", "Prof."];
const RATINGS = ["", "HOT", "WARM", "COLD"];
const LEAD_SOURCES = ["", "Web", "Phone Inquiry", "Partner Referral", "Purchased List", "Advertisement",
  "Employee Referral", "External Referral", "Public Relations", "Campaign", "Trade Show", "Word of mouth", "Other"];

export default function NewLeadModal({
  open,
  onClose,
  onCreated,
  campaigns,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (lead: LeadOut) => void;
  campaigns: CampaignOut[];
}) {
  const api = useApi();
  const dispatch = useAppDispatch();
  const { isVisible, isEditable } = useFieldPermissions("LEAD");
  const { isVisible: accountIsVisible, isEditable: accountIsEditable } = useFieldPermissions("ACCOUNT");
  const [draft, setDraft] = useState<Draft>(BLANK);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [accountMode, setAccountMode] = useState<AccountMode>("existing");
  const [accountDraft, setAccountDraft] = useState<AccountDraft>(BLANK_ACCOUNT_DRAFT);
  const [accountErrors, setAccountErrors] = useState<Record<string, string>>({});
  const [isPending, startTransition] = useTransition();
  const [accounts, setAccounts] = useState<AccountOut[] | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    listAccounts(api, { page_size: 100 })
      .then((page) => {
        if (!cancelled) setAccounts(page.items);
      })
      .catch(() => {
        if (!cancelled) setAccounts([]);
      });
    return () => {
      cancelled = true;
    };
  }, [open, api]);

  function selectAccount(accountId: string) {
    const account = accounts?.find((a) => a.id === accountId) ?? null;
    setDraft((prev) => ({
      ...prev,
      account_id: accountId,
      ...(account
        ? {
            ...leadFieldsFromAccount(account),
            industry: matchIndustry(account.industry),
            city: account.billing_city ?? "",
            postal_code: account.billing_postal_code ?? "",
          }
        : {}),
    }));
  }

  function close() {
    setDraft(BLANK);
    setErrors({});
    setAccountMode("existing");
    setAccountDraft(BLANK_ACCOUNT_DRAFT);
    setAccountErrors({});
    onClose();
  }

  function submit() {
    const e: Record<string, string> = {};
    if (accountMode === "existing" && !draft.company_name.trim()) e.company_name = "Company name is required.";
    if (!draft.last_name.trim()) e.last_name = "Last name is required.";
    if (!draft.contact_email.trim()) {
      e.contact_email = "Email is required.";
    } else if (!EMAIL_RE.test(draft.contact_email.trim())) {
      e.contact_email = "Please enter a valid email address.";
    }
    setErrors(e);

    const accE = accountMode === "new" ? validateAccountDraft(accountDraft) : {};
    setAccountErrors(accE);
    if (Object.keys(e).length > 0 || Object.keys(accE).length > 0) return;

    startTransition(async () => {
      try {
        // Creating a new Account inline supplies the same company-level
        // fields (name, industry, website, phone, address, country/state,
        // revenue, employees, rating) an existing-Account selection would
        // — see leadFieldsFromAccount(). Those fields are hidden from the
        // Lead-specific section below in this mode so they're never entered
        // twice (see the isVisible(...) guards further down).
        let accountId: string | null = draft.account_id || null;
        let companyFields: Partial<LeadCreatePayload> = {};
        if (accountMode === "new") {
          const createdAccount = await createAccount(api, accountDraftToPayload(accountDraft));
          dispatch(showToast("Account saved successfully."));
          accountId = createdAccount.id;
          const fields = leadFieldsFromAccount(createdAccount);
          companyFields = {
            company_name: fields.company_name,
            industry: fields.industry || null,
            website: fields.website || null,
            contact_phone: fields.contact_phone || null,
            address: fields.address || null,
            country: fields.country || null,
            state_province: fields.state_province || null,
            city: createdAccount.billing_city || null,
            postal_code: createdAccount.billing_postal_code || null,
            annual_revenue: fields.annual_revenue ? Number(fields.annual_revenue) : null,
            num_employees: fields.num_employees ? Number(fields.num_employees) : null,
            rating: fields.rating || null,
          };
        }
        const payload: LeadCreatePayload = {
          account_id: accountId,
          company_name: draft.company_name.trim(),
          salutation: draft.salutation || null,
          first_name: draft.first_name.trim() || null,
          last_name: draft.last_name.trim(),
          title: draft.title.trim() || null,
          contact_email: draft.contact_email.trim(),
          contact_phone: draft.contact_phone.trim() || null,
          mobile_phone: draft.mobile_phone.trim() || null,
          website: draft.website.trim() || null,
          linkedin_url: draft.linkedin_url.trim() || null,
          industry: draft.industry.trim() || null,
          rating: draft.rating || null,
          annual_revenue: draft.annual_revenue.trim() ? Number(draft.annual_revenue) : null,
          num_employees: draft.num_employees.trim() ? Number(draft.num_employees) : null,
          campaign_id: draft.campaign_id || null,
          source: draft.source || null,
          address: draft.address.trim() || null,
          country: draft.country || null,
          state_province: draft.state_province || null,
          city: draft.city.trim() || null,
          postal_code: draft.postal_code.trim() || null,
          description: draft.description.trim() || null,
          do_not_call: draft.do_not_call,
          email_opt_out: draft.email_opt_out,
          ...companyFields,
        };
        const created = await createLead(api, payload);
        dispatch(showToast("Lead saved successfully."));
        onCreated(created);
        close();
      } catch (err) {
        if (err instanceof ApiError && err.fields) {
          const fieldErrors: Record<string, string> = {};
          for (const f of err.fields) fieldErrors[String(f.loc[f.loc.length - 1])] = f.msg;
          setErrors(fieldErrors);
        } else {
          setErrors({ company_name: err instanceof ApiError ? err.message : "Failed to create lead." });
        }
      }
    });
  }

  // Lead-level fields. In "Create New Account" mode they render inside their own
  // outlined "Lead details" section (below the Account fields); in "Select Existing
  // Account" mode they render straight into the form grid, as before.
  const leadFields = (
    <>
      {isVisible("salutation") && (
        <div className="field">
          <div className="lab">Salutation</div>
          <select className="inp" disabled={!isEditable("salutation")} value={draft.salutation}
                 onChange={(e) => setDraft({ ...draft, salutation: e.target.value })}>
            {SALUTATIONS.map((s) => <option key={s} value={s}>{s || "—"}</option>)}
          </select>
        </div>
      )}
      {isVisible("first_name") && (
        <div className="field">
          <div className="lab">First name</div>
          <input className="inp" disabled={!isEditable("first_name")} value={draft.first_name}
                onChange={(e) => setDraft({ ...draft, first_name: e.target.value })} autoFocus />
        </div>
      )}
      <div className="field">
        <div className="lab">Last name <span className="req">*</span></div>
        <input className="inp" value={draft.last_name} onChange={(e) => setDraft({ ...draft, last_name: e.target.value })} />
        {errors.last_name && <div className="help err">{errors.last_name}</div>}
      </div>

      {accountMode === "existing" && (
        <div className="field" style={{ gridColumn: "1 / -1" }}>
          <div className="lab">Company <span className="req">*</span></div>
          <input className="inp" value={draft.company_name} onChange={(e) => setDraft({ ...draft, company_name: e.target.value })} />
          {errors.company_name && <div className="help err">{errors.company_name}</div>}
        </div>
      )}

      {isVisible("title") && (
        <div className="field">
          <div className="lab">Title</div>
          <input className="inp" disabled={!isEditable("title")} value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
        </div>
      )}
      {isVisible("industry") && accountMode === "existing" && (
        <div className="field">
          <div className="lab">Industry</div>
          <IndustrySelect disabled={!isEditable("industry")} value={draft.industry} onChange={(industry) => setDraft({ ...draft, industry })} />
        </div>
      )}
      {isVisible("rating") && accountMode === "existing" && (
        <div className="field">
          <div className="lab">Rating</div>
          <select className="inp" disabled={!isEditable("rating")} value={draft.rating} onChange={(e) => setDraft({ ...draft, rating: e.target.value })}>
            {RATINGS.map((r) => <option key={r} value={r}>{r || "—"}</option>)}
          </select>
        </div>
      )}

      {isVisible("contact_email") && (
        <div className="field">
          <div className="lab">Email <span className="req">*</span></div>
          <input className="inp" type="email" disabled={!isEditable("contact_email")} value={draft.contact_email} onChange={(e) => setDraft({ ...draft, contact_email: e.target.value })} />
          {errors.contact_email && <div className="help err">{errors.contact_email}</div>}
        </div>
      )}
      {isVisible("contact_phone") && accountMode === "existing" && (
        <div className="field">
          <div className="lab">Phone</div>
          <input className="inp" disabled={!isEditable("contact_phone")} value={draft.contact_phone} onChange={(e) => setDraft({ ...draft, contact_phone: e.target.value })} />
        </div>
      )}
      {isVisible("mobile_phone") && (
        <div className="field">
          <div className="lab">Mobile</div>
          <input className="inp" disabled={!isEditable("mobile_phone")} value={draft.mobile_phone} onChange={(e) => setDraft({ ...draft, mobile_phone: e.target.value })} />
        </div>
      )}

      {isVisible("website") && accountMode === "existing" && (
        <div className="field">
          <div className="lab">Website</div>
          <input className="inp" disabled={!isEditable("website")} value={draft.website} onChange={(e) => setDraft({ ...draft, website: e.target.value })} />
        </div>
      )}
      {isVisible("linkedin_url") && (
        <div className="field">
          <div className="lab">LinkedIn URL</div>
          <input
            className="inp"
            disabled={!isEditable("linkedin_url")}
            value={draft.linkedin_url}
            onChange={(e) => setDraft({ ...draft, linkedin_url: e.target.value })}
            placeholder="https://www.linkedin.com/in/..."
          />
        </div>
      )}
      {isVisible("annual_revenue") && accountMode === "existing" && (
        <div className="field">
          <div className="lab">Annual revenue</div>
          <input className="inp" type="number" disabled={!isEditable("annual_revenue")} value={draft.annual_revenue} onChange={(e) => setDraft({ ...draft, annual_revenue: e.target.value })} />
        </div>
      )}
      {isVisible("num_employees") && accountMode === "existing" && (
        <div className="field">
          <div className="lab">No. of employees</div>
          <EmployeeRangeSelect disabled={!isEditable("num_employees")} value={draft.num_employees} onChange={(num_employees) => setDraft({ ...draft, num_employees })} />
        </div>
      )}

      {isVisible("source") && (
        <div className="field">
          <div className="lab">Lead source</div>
          <select className="inp" disabled={!isEditable("source")} value={draft.source} onChange={(e) => setDraft({ ...draft, source: e.target.value })}>
            {LEAD_SOURCES.map((s) => <option key={s} value={s}>{s || "—"}</option>)}
          </select>
        </div>
      )}
      {isVisible("campaign_id") && (
        <div className="field" style={{ gridColumn: "2 / -1" }}>
          <div className="lab">Campaign</div>
          <select className="inp" disabled={!isEditable("campaign_id")} value={draft.campaign_id} onChange={(e) => setDraft({ ...draft, campaign_id: e.target.value })}>
            <option value="">None</option>
            {campaigns.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
      )}

      {accountMode === "existing" && (
        <AddressSection
          title="Address"
          labels={{
            street: "Street",
            city: "City",
            state_province: "State/Province",
            country: "Country",
            postal_code: "Postal code",
          }}
          fields={{
            street: "address",
            city: "city",
            state_province: "state_province",
            country: "country",
            postal_code: "postal_code",
          }}
          values={{
            street: draft.address,
            city: draft.city,
            state_province: draft.state_province,
            country: draft.country,
            postal_code: draft.postal_code,
          }}
          onChange={(a) => setDraft({
            ...draft,
            address: a.street,
            city: a.city,
            state_province: a.state_province,
            country: a.country,
            postal_code: a.postal_code,
          })}
          isVisible={isVisible}
          isEditable={isEditable}
        />
      )}
      {isVisible("description") && (
        <div className="field" style={{ gridColumn: "1 / -1" }}>
          <div className="lab">Description</div>
          <textarea className="inp" rows={3} disabled={!isEditable("description")} value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
        </div>
      )}

      {isVisible("do_not_call") && (
        <div className="field" style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
          <input type="checkbox" disabled={!isEditable("do_not_call")} checked={draft.do_not_call} onChange={(e) => setDraft({ ...draft, do_not_call: e.target.checked })} id="lead-dnc" />
          <label htmlFor="lead-dnc" className="lab" style={{ margin: 0 }}>Do not call</label>
        </div>
      )}
      {isVisible("email_opt_out") && (
        <div className="field" style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
          <input type="checkbox" disabled={!isEditable("email_opt_out")} checked={draft.email_opt_out} onChange={(e) => setDraft({ ...draft, email_opt_out: e.target.checked })} id="lead-optout" />
          <label htmlFor="lead-optout" className="lab" style={{ margin: 0 }}>Email opt out</label>
        </div>
      )}
    </>
  );

  return (
    <Modal
      open={open}
      onClose={close}
      title="New Lead"
      footer={
        <>
          <button className="btn sm" onClick={close} disabled={isPending}>Cancel</button>
          <div className="spacer" />
          <button className="btn primary sm" onClick={submit} disabled={isPending}>
            {isPending ? "Saving…" : "Save"}
          </button>
        </>
      }
    >
      <div className="fields" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
        {isVisible("account_id") && (
          <div className="field" style={{ gridColumn: "1 / -1" }}>
            <div className="lab">Account</div>
            <div style={{ display: "flex", gap: 20, margin: "2px 0 8px" }}>
              <label style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 400 }}>
                <input
                  type="radio"
                  name="lead-account-mode"
                  checked={accountMode === "existing"}
                  onChange={() => setAccountMode("existing")}
                />
                Select Existing Account
              </label>
              <label style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 400 }}>
                <input
                  type="radio"
                  name="lead-account-mode"
                  checked={accountMode === "new"}
                  onChange={() => setAccountMode("new")}
                />
                Create New Account
              </label>
            </div>
            {accountMode === "existing" && (
              <>
                <select
                  className="inp"
                  disabled={!isEditable("account_id") || accounts === null}
                  value={draft.account_id}
                  onChange={(e) => selectAccount(e.target.value)}
                >
                  <option value="">{accounts === null ? "Loading…" : "Select account…"}</option>
                  {accounts?.map((a) => (
                    <option key={a.id} value={a.id}>{a.legal_name} ({a.id})</option>
                  ))}
                </select>
                <div className="help">Selecting an existing account fills in the company fields below.</div>
              </>
            )}
          </div>
        )}
        {isVisible("account_id") && accountMode === "new" && (
          <div
            className="fields"
            style={{
              gridColumn: "1 / -1",
              gridTemplateColumns: "repeat(2, 1fr)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              padding: 12,
              marginBottom: 4,
            }}
          >
            <AccountFormFields
              draft={accountDraft}
              setDraft={setAccountDraft}
              errors={accountErrors}
              isVisible={accountIsVisible}
              isEditable={accountIsEditable}
            />
          </div>
        )}
        {accountMode === "new" ? (
          <>
            <div className="lab" style={{ gridColumn: "1 / -1", marginTop: 4 }}>Lead details</div>
            <div
              className="fields"
              style={{
                gridColumn: "1 / -1",
                gridTemplateColumns: "repeat(3, 1fr)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                padding: 12,
                marginBottom: 4,
              }}
            >
              {leadFields}
            </div>
          </>
        ) : (
          leadFields
        )}
      </div>
    </Modal>
  );
}
