"use client";

import { useState, useTransition } from "react";
import Modal from "../Modal";
import { ApiError, useApi } from "@/lib/api/client";
import { createAgreement, type AgreementCreatePayload, type AgreementOut } from "@/lib/api/contracts";
import type { AccountOut } from "@/lib/api/crm";

/** Matches the seeded agreement_type lookup rows (see Admin > Lookups). */
const AGREEMENT_TYPES = [
  { code: "NDA", label: "NDA" },
  { code: "MSA", label: "MSA" },
  { code: "SOW", label: "SOW" },
  { code: "VENDOR_MSA", label: "Vendor MSA" },
  { code: "PURCHASE_ORDER", label: "Purchase Order" },
];

interface Draft {
  account_id: string;
  agreement_type: string;
  title: string;
  effective_date: string;
  expiry_date: string;
  contract_term_months: string;
  owner_expiration_notice_days: string;
  billing_address: string;
  special_terms: string;
}

const BLANK: Draft = {
  account_id: "",
  agreement_type: "",
  title: "",
  effective_date: "",
  expiry_date: "",
  contract_term_months: "",
  owner_expiration_notice_days: "",
  billing_address: "",
  special_terms: "",
};

function validate(d: Draft, requireAccount: boolean): Record<string, string> {
  const e: Record<string, string> = {};
  if (requireAccount && !d.account_id) e.account_id = "Account is required.";
  if (!d.agreement_type) e.agreement_type = "Agreement type is required.";
  if (!d.title.trim()) e.title = "Title is required.";
  if (d.effective_date && d.expiry_date && d.expiry_date <= d.effective_date) {
    e.expiry_date = "Expiry date must be after the effective date.";
  }
  return e;
}

export default function NewAgreementModal({
  open,
  onClose,
  onCreated,
  accountId,
  accounts,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (agreement: AgreementOut) => void;
  /** Fixed account (e.g. opened from an account's Agreements tab) — hides the picker. */
  accountId?: string;
  /** Account picker options, required when accountId isn't fixed. */
  accounts?: AccountOut[];
}) {
  const api = useApi();
  const [draft, setDraft] = useState<Draft>(BLANK);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isPending, startTransition] = useTransition();

  function reset() {
    setDraft(BLANK);
    setErrors({});
  }

  function close() {
    reset();
    onClose();
  }

  function submit() {
    const e = validate(draft, accountId === undefined);
    setErrors(e);
    if (Object.keys(e).length > 0) return;

    startTransition(async () => {
      try {
        const payload: AgreementCreatePayload = {
          account_id: accountId ?? draft.account_id,
          agreement_type: draft.agreement_type,
          title: draft.title.trim(),
          effective_date: draft.effective_date || null,
          expiry_date: draft.expiry_date || null,
          contract_term_months: draft.contract_term_months.trim() ? Number(draft.contract_term_months) : null,
          owner_expiration_notice_days: draft.owner_expiration_notice_days.trim() ? Number(draft.owner_expiration_notice_days) : null,
          billing_address: draft.billing_address.trim() || null,
          special_terms: draft.special_terms.trim() || null,
        };
        const created = await createAgreement(api, payload);
        onCreated(created);
        close();
      } catch (err) {
        if (err instanceof ApiError && err.fields) {
          const fieldErrors: Record<string, string> = {};
          for (const f of err.fields) {
            const key = String(f.loc[f.loc.length - 1]);
            fieldErrors[key] = f.msg;
          }
          setErrors(fieldErrors);
        } else {
          setErrors({ title: err instanceof ApiError ? err.message : "Failed to create agreement." });
        }
      }
    });
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title="New Agreement"
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
      <div className="fields" style={{ gridTemplateColumns: "repeat(2, 1fr)" }}>
        {accountId === undefined && (
          <div className="field" style={{ gridColumn: "1 / -1" }}>
            <div className="lab">Account <span className="req">*</span></div>
            <select
              className="inp"
              value={draft.account_id}
              onChange={(e) => setDraft({ ...draft, account_id: e.target.value })}
              disabled={accounts === undefined}
            >
              <option value="">{accounts === undefined ? "Loading…" : "Select…"}</option>
              {accounts?.map((c) => (
                <option key={c.id} value={c.id}>{c.legal_name} ({c.id})</option>
              ))}
            </select>
            {errors.account_id && <div className="help err">{errors.account_id}</div>}
          </div>
        )}
        <div className="field" style={{ gridColumn: "1 / -1" }}>
          <div className="lab">Title <span className="req">*</span></div>
          <input
            className="inp"
            value={draft.title}
            onChange={(e) => setDraft({ ...draft, title: e.target.value })}
            autoFocus
          />
          {errors.title && <div className="help err">{errors.title}</div>}
        </div>
        <div className="field">
          <div className="lab">Type <span className="req">*</span></div>
          <select
            className="inp"
            value={draft.agreement_type}
            onChange={(e) => setDraft({ ...draft, agreement_type: e.target.value })}
          >
            <option value="">Select…</option>
            {AGREEMENT_TYPES.map((t) => (
              <option key={t.code} value={t.code}>{t.label}</option>
            ))}
          </select>
          {errors.agreement_type && <div className="help err">{errors.agreement_type}</div>}
        </div>
        <div className="field">
          <div className="lab">Effective date</div>
          <input
            type="date"
            className="inp"
            value={draft.effective_date}
            onChange={(e) => setDraft({ ...draft, effective_date: e.target.value })}
          />
        </div>
        <div className="field">
          <div className="lab">Expiry date</div>
          <input
            type="date"
            className="inp"
            value={draft.expiry_date}
            onChange={(e) => setDraft({ ...draft, expiry_date: e.target.value })}
          />
          {errors.expiry_date && <div className="help err">{errors.expiry_date}</div>}
        </div>
        <div className="field">
          <div className="lab">Contract term (months)</div>
          <input
            className="inp"
            type="number"
            value={draft.contract_term_months}
            onChange={(e) => setDraft({ ...draft, contract_term_months: e.target.value })}
          />
        </div>
        <div className="field">
          <div className="lab">Owner expiration notice (days)</div>
          <input
            className="inp"
            type="number"
            value={draft.owner_expiration_notice_days}
            onChange={(e) => setDraft({ ...draft, owner_expiration_notice_days: e.target.value })}
          />
        </div>
        <div className="field" style={{ gridColumn: "1 / -1" }}>
          <div className="lab">Billing address</div>
          <textarea className="inp" value={draft.billing_address} onChange={(e) => setDraft({ ...draft, billing_address: e.target.value })} />
        </div>
        <div className="field" style={{ gridColumn: "1 / -1" }}>
          <div className="lab">Special terms</div>
          <textarea className="inp" rows={3} value={draft.special_terms} onChange={(e) => setDraft({ ...draft, special_terms: e.target.value })} />
        </div>
        <div className="help" style={{ gridColumn: "1 / -1" }}>
          New agreements always start as Draft — add running notes and set the governing MSA/project (for a SOW) afterward from its detail page.
        </div>
      </div>
    </Modal>
  );
}
