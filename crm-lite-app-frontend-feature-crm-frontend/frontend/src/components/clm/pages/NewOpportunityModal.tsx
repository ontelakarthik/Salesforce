"use client";

import { useEffect, useState, useTransition } from "react";
import Modal from "../Modal";
import { ApiError, useApi } from "@/lib/api/client";
import {
  createOpportunity,
  listAccounts,
  type AccountOut,
  type OpportunityCreatePayload,
  type OpportunityOut,
} from "@/lib/api/crm";
import { useFieldPermissions } from "@/lib/api/fieldPermissions";

interface Draft {
  account_id: string;
  name: string;
  estimated_value: string;
  currency: string;
  expected_close_date: string;
  probability_percent: string;
  opportunity_type: string;
  next_step: string;
  description: string;
}

const BLANK: Draft = {
  account_id: "",
  name: "",
  estimated_value: "",
  currency: "USD",
  expected_close_date: "",
  probability_percent: "",
  opportunity_type: "",
  next_step: "",
  description: "",
};

const OPPORTUNITY_TYPES = ["", "NEW_BUSINESS", "EXISTING_BUSINESS", "RENEWAL"];

function validate(d: Draft, requireAccount: boolean): Record<string, string> {
  const e: Record<string, string> = {};
  if (requireAccount && !d.account_id) e.account_id = "Account is required.";
  if (!d.name.trim()) e.name = "Deal name is required.";
  if (d.estimated_value.trim() && Number.isNaN(Number(d.estimated_value))) {
    e.estimated_value = "Enter a valid number.";
  }
  return e;
}

export default function NewOpportunityModal({
  open,
  onClose,
  onCreated,
  accountId,
  originatingAssetId,
}: {
  open: boolean;
  onClose: () => void;
  /** andNew=true means the modal stays open (Save & New) — don't navigate away on this call. */
  onCreated: (opportunity: OpportunityOut, andNew: boolean) => void;
  /** Fixed account (e.g. opened from an account's own page) — hides the picker. */
  accountId?: string;
  /** Set when this is a renewal/cross-sell against an existing Asset — the
   * created Opportunity auto-inherits that Asset's originating campaign. */
  originatingAssetId?: string;
}) {
  const api = useApi();
  const { isVisible, isEditable } = useFieldPermissions("OPPORTUNITY");
  const [draft, setDraft] = useState<Draft>(BLANK);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isPending, startTransition] = useTransition();
  const [accounts, setAccounts] = useState<AccountOut[] | null>(null);

  useEffect(() => {
    if (!open || accountId !== undefined) return;
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
  }, [open, api, accountId]);

  function reset() {
    setDraft(BLANK);
    setErrors({});
  }

  function close() {
    reset();
    onClose();
  }

  function submit(andNew: boolean) {
    const e = validate(draft, accountId === undefined);
    setErrors(e);
    if (Object.keys(e).length > 0) return;

    startTransition(async () => {
      try {
        const payload: OpportunityCreatePayload = {
          account_id: accountId ?? draft.account_id,
          name: draft.name.trim(),
          estimated_value: draft.estimated_value.trim() ? Number(draft.estimated_value) : null,
          currency: draft.currency || "USD",
          expected_close_date: draft.expected_close_date || null,
          probability_percent: draft.probability_percent.trim() ? Number(draft.probability_percent) : null,
          opportunity_type: draft.opportunity_type || null,
          next_step: draft.next_step.trim() || null,
          description: draft.description.trim() || null,
          originating_asset_id: originatingAssetId ?? null,
        };
        const created = await createOpportunity(api, payload);
        onCreated(created, andNew);
        if (andNew) {
          reset();
        } else {
          close();
        }
      } catch (err) {
        if (err instanceof ApiError && err.fields) {
          const fieldErrors: Record<string, string> = {};
          for (const f of err.fields) {
            const key = String(f.loc[f.loc.length - 1]);
            fieldErrors[key] = f.msg;
          }
          setErrors(fieldErrors);
        } else {
          setErrors({ name: err instanceof ApiError ? err.message : "Failed to create opportunity." });
        }
      }
    });
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title={originatingAssetId ? "Start renewal" : "New Opportunity"}
      footer={
        <>
          <button className="btn sm" onClick={close} disabled={isPending}>Cancel</button>
          <div className="spacer" />
          <button className="btn sm" onClick={() => submit(true)} disabled={isPending}>Save &amp; New</button>
          <button className="btn primary sm" onClick={() => submit(false)} disabled={isPending}>
            {isPending ? "Saving…" : "Save"}
          </button>
        </>
      }
    >
      <div className="fields" style={{ gridTemplateColumns: "repeat(2, 1fr)" }}>
        {originatingAssetId && (
          <div className="help" style={{ gridColumn: "1 / -1", marginBottom: 4 }}>
            This Opportunity will be linked back to the Asset it&apos;s renewing, and will automatically
            inherit the campaign that originally brought this account in.
          </div>
        )}
        {accountId === undefined && (
          <div className="field" style={{ gridColumn: "1 / -1" }}>
            <div className="lab">Account <span className="req">*</span></div>
            <select
              className="inp"
              value={draft.account_id}
              onChange={(e) => setDraft({ ...draft, account_id: e.target.value })}
              disabled={accounts === null}
            >
              <option value="">{accounts === null ? "Loading…" : "Select…"}</option>
              {accounts?.map((c) => (
                <option key={c.id} value={c.id}>{c.legal_name} ({c.id})</option>
              ))}
            </select>
            {errors.account_id && <div className="help err">{errors.account_id}</div>}
          </div>
        )}
        <div className="field" style={{ gridColumn: "1 / -1" }}>
          <div className="lab">Deal name <span className="req">*</span></div>
          <input
            className="inp"
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            autoFocus
          />
          {errors.name && <div className="help err">{errors.name}</div>}
        </div>
        {isVisible("estimated_value") && (
          <div className="field">
            <div className="lab">Estimated value</div>
            <input
              className="inp"
              type="number"
              disabled={!isEditable("estimated_value")}
              value={draft.estimated_value}
              onChange={(e) => setDraft({ ...draft, estimated_value: e.target.value })}
            />
            {errors.estimated_value && <div className="help err">{errors.estimated_value}</div>}
          </div>
        )}
        {isVisible("currency") && (
          <div className="field">
            <div className="lab">Currency</div>
            <input
              className="inp"
              disabled={!isEditable("currency")}
              value={draft.currency}
              maxLength={3}
              onChange={(e) => setDraft({ ...draft, currency: e.target.value.toUpperCase() })}
            />
          </div>
        )}
        {isVisible("expected_close_date") && (
          <div className="field">
            <div className="lab">Expected close</div>
            <input
              type="date"
              className="inp"
              disabled={!isEditable("expected_close_date")}
              value={draft.expected_close_date}
              onChange={(e) => setDraft({ ...draft, expected_close_date: e.target.value })}
            />
          </div>
        )}
        {isVisible("probability_percent") && (
          <div className="field">
            <div className="lab">Probability %</div>
            <input
              className="inp"
              type="number"
              disabled={!isEditable("probability_percent")}
              value={draft.probability_percent}
              onChange={(e) => setDraft({ ...draft, probability_percent: e.target.value })}
            />
          </div>
        )}
        {isVisible("opportunity_type") && (
          <div className="field">
            <div className="lab">Opportunity type</div>
            <select
              className="inp"
              disabled={!isEditable("opportunity_type")}
              value={draft.opportunity_type}
              onChange={(e) => setDraft({ ...draft, opportunity_type: e.target.value })}
            >
              {OPPORTUNITY_TYPES.map((t) => <option key={t} value={t}>{t ? t.replace("_", " ") : "—"}</option>)}
            </select>
          </div>
        )}
        {isVisible("next_step") && (
          <div className="field" style={{ gridColumn: "1 / -1" }}>
            <div className="lab">Next step</div>
            <input
              className="inp"
              disabled={!isEditable("next_step")}
              value={draft.next_step}
              onChange={(e) => setDraft({ ...draft, next_step: e.target.value })}
            />
          </div>
        )}
        {isVisible("description") && (
          <div className="field" style={{ gridColumn: "1 / -1" }}>
            <div className="lab">Description</div>
            <textarea
              className="inp"
              rows={3}
              disabled={!isEditable("description")}
              value={draft.description}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })}
            />
          </div>
        )}
      </div>
    </Modal>
  );
}
