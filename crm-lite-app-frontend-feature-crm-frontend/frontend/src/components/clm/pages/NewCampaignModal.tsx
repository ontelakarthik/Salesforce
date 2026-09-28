"use client";

import { useState, useTransition } from "react";
import Modal from "../Modal";
import { ApiError, useApi } from "@/lib/api/client";
import { createCampaign, type CampaignCreatePayload, type CampaignOut } from "@/lib/api/crm";

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
}

const BLANK: Draft = {
  name: "",
  campaign_type: "WEBINAR",
  other_type: "",
  status: "PLANNED",
  start_date: "",
  end_date: "",
  description: "",
  budgeted_cost: "",
  actual_cost: "",
  expected_revenue: "",
  expected_response_pct: "",
  num_sent: "",
};

const CAMPAIGN_TYPES = ["WEBINAR", "EMAIL", "EVENT", "OTHER"];
const CAMPAIGN_STATUSES = ["PLANNED", "IN_PROGRESS", "COMPLETED", "ABORTED"];

export default function NewCampaignModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (campaign: CampaignOut) => void;
}) {
  const api = useApi();
  const [draft, setDraft] = useState<Draft>(BLANK);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  function close() {
    setDraft(BLANK);
    setError(null);
    onClose();
  }

  function submit() {
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
        const payload: CampaignCreatePayload = {
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
        };
        const created = await createCampaign(api, payload);
        onCreated(created);
        close();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to create campaign.");
      }
    });
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title="New Campaign"
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
        <div className="field" style={{ gridColumn: "1 / -1" }}>
          <div className="lab">Campaign name <span className="req">*</span></div>
          <input className="inp" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} autoFocus />
          {error && <div className="help err">{error}</div>}
        </div>
        <div className="field">
          <div className="lab">Type</div>
          <select className="inp" value={draft.campaign_type} onChange={(e) => setDraft({ ...draft, campaign_type: e.target.value })}>
            {CAMPAIGN_TYPES.map((t) => <option key={t} value={t}>{t.charAt(0) + t.slice(1).toLowerCase()}</option>)}
          </select>
        </div>
        <div className="field">
          <div className="lab">Status</div>
          <select className="inp" value={draft.status} onChange={(e) => setDraft({ ...draft, status: e.target.value })}>
            {CAMPAIGN_STATUSES.map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
          </select>
        </div>
        {draft.campaign_type === "OTHER" ? (
          <div className="field">
            <div className="lab">Specify type <span className="req">*</span></div>
            <input
              className="inp"
              value={draft.other_type}
              onChange={(e) => setDraft({ ...draft, other_type: e.target.value })}
              placeholder="e.g. Trade show"
            />
          </div>
        ) : <div />}
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
