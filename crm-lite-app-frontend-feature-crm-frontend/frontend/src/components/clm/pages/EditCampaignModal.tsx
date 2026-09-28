"use client";

import { useEffect, useState, useTransition } from "react";
import Modal from "../Modal";
import { ApiError, useApi } from "@/lib/api/client";
import { updateCampaign, type CampaignOut, type CampaignUpdatePayload } from "@/lib/api/crm";

interface Draft {
  name: string;
  campaign_type: string;
  other_type: string;
  status: string;
  start_date: string;
  end_date: string;
  description: string;
  budgeted_cost: string;
  actual_cost: string;
  expected_revenue: string;
  expected_response_pct: string;
  num_sent: string;
  is_active: boolean;
}

const CAMPAIGN_TYPES = ["WEBINAR", "EMAIL", "EVENT", "OTHER"];
const CAMPAIGN_STATUSES = ["PLANNED", "IN_PROGRESS", "COMPLETED", "ABORTED"];

function toDraft(campaign: CampaignOut): Draft {
  const knownType = campaign.campaign_type && CAMPAIGN_TYPES.includes(campaign.campaign_type);
  return {
    name: campaign.name,
    campaign_type: campaign.campaign_type ? (knownType ? campaign.campaign_type : "OTHER") : "",
    other_type: campaign.campaign_type && !knownType ? campaign.campaign_type : "",
    status: campaign.status ?? "",
    start_date: campaign.start_date ?? "",
    end_date: campaign.end_date ?? "",
    description: campaign.description ?? "",
    budgeted_cost: campaign.budgeted_cost != null ? String(campaign.budgeted_cost) : "",
    actual_cost: campaign.actual_cost != null ? String(campaign.actual_cost) : "",
    expected_revenue: campaign.expected_revenue != null ? String(campaign.expected_revenue) : "",
    expected_response_pct: campaign.expected_response_pct != null ? String(campaign.expected_response_pct) : "",
    num_sent: campaign.num_sent != null ? String(campaign.num_sent) : "",
    is_active: campaign.is_active,
  };
}

export default function EditCampaignModal({
  campaign,
  onClose,
  onSaved,
}: {
  campaign: CampaignOut | null;
  onClose: () => void;
  onSaved: (campaign: CampaignOut) => void;
}) {
  const api = useApi();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    if (campaign) {
      setDraft(toDraft(campaign));
      setError(null);
    }
  }, [campaign]);

  function submit() {
    if (!campaign || !draft) return;
    if (!draft.name.trim()) {
      setError("Campaign name is required.");
      return;
    }
    if (draft.campaign_type === "OTHER" && !draft.other_type.trim()) {
      setError("Enter what kind of campaign this is.");
      return;
    }
    startTransition(async () => {
      try {
        const payload: CampaignUpdatePayload = {
          name: draft.name.trim(),
          campaign_type: draft.campaign_type === "OTHER" ? draft.other_type.trim() : draft.campaign_type || null,
          status: draft.status || null,
          start_date: draft.start_date || null,
          end_date: draft.end_date || null,
          description: draft.description.trim() || null,
          budgeted_cost: draft.budgeted_cost.trim() ? Number(draft.budgeted_cost) : null,
          actual_cost: draft.actual_cost.trim() ? Number(draft.actual_cost) : null,
          expected_revenue: draft.expected_revenue.trim() ? Number(draft.expected_revenue) : null,
          expected_response_pct: draft.expected_response_pct.trim() ? Number(draft.expected_response_pct) : null,
          num_sent: draft.num_sent.trim() ? Number(draft.num_sent) : null,
          is_active: draft.is_active,
        };
        const updated = await updateCampaign(api, campaign.id, payload);
        onSaved(updated);
        onClose();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to save campaign.");
      }
    });
  }

  if (!campaign || !draft) return null;

  return (
    <Modal
      open={campaign !== null}
      onClose={onClose}
      title={`Edit ${campaign.name}`}
      footer={
        <>
          <button className="btn sm" onClick={onClose} disabled={isPending}>Cancel</button>
          <div className="spacer" />
          <button className="btn primary sm" onClick={submit} disabled={isPending}>
            {isPending ? "Saving…" : "Save"}
          </button>
        </>
      }
    >
      <div className="fields" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
        <div className="field" style={{ gridColumn: "1 / -1" }}>
          <div className="lab">Campaign name <span className="req">*</span></div>
          <input className="inp" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} autoFocus />
          {error && <div className="help err">{error}</div>}
        </div>
        <div className="field">
          <div className="lab">Type</div>
          <select className="inp" value={draft.campaign_type} onChange={(e) => setDraft({ ...draft, campaign_type: e.target.value })}>
            <option value="">—</option>
            {CAMPAIGN_TYPES.map((t) => <option key={t} value={t}>{t.charAt(0) + t.slice(1).toLowerCase()}</option>)}
          </select>
        </div>
        {draft.campaign_type === "OTHER" && (
          <div className="field">
            <div className="lab">Specify type <span className="req">*</span></div>
            <input
              className="inp"
              value={draft.other_type}
              onChange={(e) => setDraft({ ...draft, other_type: e.target.value })}
              placeholder="e.g. Trade show"
            />
          </div>
        )}
        <div className="field">
          <div className="lab">Status</div>
          <select className="inp" value={draft.status} onChange={(e) => setDraft({ ...draft, status: e.target.value })}>
            <option value="">—</option>
            {CAMPAIGN_STATUSES.map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
          </select>
        </div>
        <div className="field">
          <label className="val" style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 22 }}>
            <input
              type="checkbox"
              checked={draft.is_active}
              onChange={(e) => setDraft({ ...draft, is_active: e.target.checked })}
            />
            Active
          </label>
        </div>
        <div className="field">
          <div className="lab">Start date</div>
          <input type="date" className="inp" value={draft.start_date} onChange={(e) => setDraft({ ...draft, start_date: e.target.value })} />
        </div>
        <div className="field">
          <div className="lab">End date</div>
          <input type="date" className="inp" value={draft.end_date} onChange={(e) => setDraft({ ...draft, end_date: e.target.value })} />
        </div>
        <div className="field">
          <div className="lab">Budgeted cost</div>
          <input className="inp" type="number" value={draft.budgeted_cost} onChange={(e) => setDraft({ ...draft, budgeted_cost: e.target.value })} />
        </div>
        <div className="field">
          <div className="lab">Actual cost</div>
          <input className="inp" type="number" value={draft.actual_cost} onChange={(e) => setDraft({ ...draft, actual_cost: e.target.value })} />
        </div>
        <div className="field">
          <div className="lab">Expected revenue</div>
          <input className="inp" type="number" value={draft.expected_revenue} onChange={(e) => setDraft({ ...draft, expected_revenue: e.target.value })} />
        </div>
        <div className="field">
          <div className="lab">Expected response %</div>
          <input className="inp" type="number" value={draft.expected_response_pct} onChange={(e) => setDraft({ ...draft, expected_response_pct: e.target.value })} />
        </div>
        <div className="field">
          <div className="lab">Num sent</div>
          <input className="inp" type="number" value={draft.num_sent} onChange={(e) => setDraft({ ...draft, num_sent: e.target.value })} />
        </div>
        <div />
        <div className="field" style={{ gridColumn: "1 / -1" }}>
          <div className="lab">Description</div>
          <textarea className="inp" rows={3} value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
        </div>
      </div>
    </Modal>
  );
}
