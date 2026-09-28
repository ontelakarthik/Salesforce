"use client";

import { useState, useTransition } from "react";
import RoleOnly from "../../RoleOnly";
import { ApiError, useApi } from "@/lib/api/client";
import { addAccountCommunication, type CommunicationCreatePayload, type CommunicationOut } from "@/lib/api/activity";

interface Draft {
  direction: string;
  channel: string;
  subject: string;
  from_address: string;
  to_recipients: string;
  cc_recipients: string;
  occurred_at: string;
}

const BLANK_COMM: Draft = {
  direction: "OUTBOUND",
  channel: "",
  subject: "",
  from_address: "",
  to_recipients: "",
  cc_recipients: "",
  occurred_at: "",
};

function formatDateTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export default function CommsPanel({
  accountId,
  initialComms,
}: {
  accountId: string;
  initialComms: CommunicationOut[];
}) {
  const api = useApi();
  const [comms, setComms] = useState<CommunicationOut[]>(initialComms);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Draft>(BLANK_COMM);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isPending, startTransition] = useTransition();

  function openForm() {
    setDraft(BLANK_COMM);
    setErrors({});
    setOpen(true);
  }

  function validate(d: Draft): Record<string, string> {
    const e: Record<string, string> = {};
    if (!d.channel.trim()) e.channel = "Channel is required.";
    if (!d.subject.trim()) e.subject = "Subject is required.";
    if (!d.occurred_at.trim()) e.occurred_at = "Date is required.";
    return e;
  }

  function save() {
    const e = validate(draft);
    setErrors(e);
    if (Object.keys(e).length > 0) return;

    startTransition(async () => {
      try {
        const payload: CommunicationCreatePayload = {
          direction: draft.direction,
          channel: draft.channel.trim(),
          subject: draft.subject.trim() || null,
          from_address: draft.from_address.trim() || null,
          to_recipients: draft.to_recipients.trim() || null,
          cc_recipients: draft.cc_recipients.trim() || null,
          occurred_at: new Date(`${draft.occurred_at}T00:00:00`).toISOString(),
        };
        const created = await addAccountCommunication(api, accountId, payload);
        setComms((prev) => [created, ...prev]);
        setOpen(false);
      } catch (err) {
        if (err instanceof ApiError && err.fields) {
          const fieldErrors: Record<string, string> = {};
          for (const f of err.fields) {
            const key = String(f.loc[f.loc.length - 1]);
            fieldErrors[key] = f.msg;
          }
          setErrors(fieldErrors);
        } else {
          setErrors({ channel: err instanceof ApiError ? err.message : "Failed to log communication." });
        }
      }
    });
  }

  return (
    <div className="card card-pad">
      {open && (
        <div style={{ marginBottom: 18, paddingBottom: 18, borderBottom: "1px solid var(--border)" }}>
          <div className="fields" style={{ gridTemplateColumns: "repeat(2, 1fr)" }}>
            <div className="field">
              <div className="lab">Direction <span className="req">*</span></div>
              <select className="inp" value={draft.direction} onChange={(e) => setDraft({ ...draft, direction: e.target.value })}>
                <option value="INBOUND">Inbound</option>
                <option value="OUTBOUND">Outbound</option>
              </select>
            </div>
            <div className="field">
              <div className="lab">Channel <span className="req">*</span></div>
              <input className="inp" value={draft.channel} onChange={(e) => setDraft({ ...draft, channel: e.target.value })} placeholder="Email, Teams, Sales DL…" />
              {errors.channel && <div className="help err">{errors.channel}</div>}
            </div>
            <div className="field">
              <div className="lab">Subject <span className="req">*</span></div>
              <input className="inp" value={draft.subject} onChange={(e) => setDraft({ ...draft, subject: e.target.value })} />
              {errors.subject && <div className="help err">{errors.subject}</div>}
            </div>
            <div className="field">
              <div className="lab">Occurred at <span className="req">*</span></div>
              <input type="date" className="inp" value={draft.occurred_at} onChange={(e) => setDraft({ ...draft, occurred_at: e.target.value })} />
              {errors.occurred_at && <div className="help err">{errors.occurred_at}</div>}
            </div>
            <div className="field">
              <div className="lab">From</div>
              <input className="inp" value={draft.from_address} onChange={(e) => setDraft({ ...draft, from_address: e.target.value })} />
            </div>
            <div className="field">
              <div className="lab">To</div>
              <input className="inp" value={draft.to_recipients} onChange={(e) => setDraft({ ...draft, to_recipients: e.target.value })} />
            </div>
            <div className="field">
              <div className="lab">Cc</div>
              <input className="inp" value={draft.cc_recipients} onChange={(e) => setDraft({ ...draft, cc_recipients: e.target.value })} />
            </div>
          </div>
          <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
            <button className="btn primary sm" onClick={save} disabled={isPending}>
              {isPending ? "Logging…" : "Log communication"}
            </button>
            <button className="btn sm" onClick={() => setOpen(false)} disabled={isPending}>Cancel</button>
          </div>
        </div>
      )}

      <div className="timeline">
        {comms.map((c) => (
          <div key={c.id} className="tl-item done">
            <div className="tl-t">{c.direction === "INBOUND" ? "Inbound" : "Outbound"} · {c.subject || "—"}</div>
            <div className="tl-d">
              via {c.channel}{c.to_recipients ? ` · to ${c.to_recipients}` : ""} · {formatDateTime(c.occurred_at)}
            </div>
          </div>
        ))}
        {comms.length === 0 && <div className="t-muted" style={{ fontSize: 13 }}>No communications logged yet.</div>}
      </div>
      <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
        <div style={{ marginTop: 14 }}>
          <button className="btn sm" onClick={openForm}>Log communication</button>
        </div>
      </RoleOnly>
    </div>
  );
}
