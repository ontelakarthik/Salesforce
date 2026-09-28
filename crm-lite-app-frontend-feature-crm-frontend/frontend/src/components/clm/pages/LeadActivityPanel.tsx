"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import Badge, { type BadgeVariant } from "../Badge";
import Dialpad from "../Dialpad";
import Modal from "../Modal";
import RoleOnly from "../RoleOnly";
import { ApiError, useApi } from "@/lib/api/client";
import { listLookups, type LookupOut } from "@/lib/api/admin";
import {
  addLeadCommunication,
  listLeadCommunications,
  sendLeadEmail,
  sendLeadSms,
  sendLeadWhatsApp,
  type CommunicationOut,
} from "@/lib/api/activity";
import { generateCallPrep, generateEmailDraft, type CallPrepOut, type EmailDraftOut, type LeadOut } from "@/lib/api/crm";
import { getLeadVoiceToken, updateCallNotes } from "@/lib/api/voice";

const FALLBACK_CALL_OUTCOMES = ["CONNECTED", "VOICEMAIL", "NO_ANSWER", "BUSY", "WRONG_NUMBER", "OTHER"];
const SMS_MAX_LENGTH = 1600;
const WHATSAPP_MAX_LENGTH = 1600;

type CallPhase = "idle" | "requesting-token" | "connecting" | "ringing" | "in-progress" | "wrapping-up" | "ended" | "failed";

const CALL_PHASE_LABEL: Record<CallPhase, string> = {
  idle: "",
  "requesting-token": "Preparing…",
  connecting: "Calling…",
  ringing: "Ringing…",
  "in-progress": "Connected",
  "wrapping-up": "Call ended — finishing up…",
  ended: "Call ended",
  failed: "Call failed",
};

const DIRECTION_BADGE: Record<string, BadgeVariant> = {
  INBOUND: "blue",
  OUTBOUND: "teal",
};

function formatDateTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function LeadActivityPanel({ lead }: { lead: LeadOut }) {
  const api = useApi();
  const [comms, setComms] = useState<CommunicationOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showLogCall, setShowLogCall] = useState(false);
  const [showSendEmail, setShowSendEmail] = useState(false);
  const [showSendSms, setShowSendSms] = useState(false);
  const [showSendWhatsApp, setShowSendWhatsApp] = useState(false);
  const [selected, setSelected] = useState<CommunicationOut | null>(null);

  function load() {
    setError(null);
    listLeadCommunications(api, lead.id)
      .then(setComms)
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Failed to load activity.");
      });
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, lead.id]);

  const sorted = comms ? [...comms].sort((a, b) => b.occurred_at.localeCompare(a.occurred_at)) : [];

  return (
    <div className="card">
      <div className="card-head">
        <h3>Activity</h3>
      </div>
      <div className="card-pad">
        <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
          <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
            <button className="btn sm" onClick={() => setShowLogCall(true)}>Log a call</button>
            <button className="btn sm" onClick={() => setShowSendEmail(true)}>Email</button>
            <button className="btn sm" onClick={() => setShowSendSms(true)}>SMS</button>
            <button className="btn sm" onClick={() => setShowSendWhatsApp(true)}>WhatsApp</button>
          </div>
        </RoleOnly>
        {error && <div className="help err" style={{ marginBottom: 14 }}>{error}</div>}
        <div className="timeline">
          {sorted.map((c) => (
            <div
              key={c.id}
              className="tl-item done"
              style={{ cursor: "pointer" }}
              onClick={() => setSelected(c)}
            >
              <div className="tl-t">
                <Badge variant={DIRECTION_BADGE[c.direction] ?? "gray"} style={{ marginRight: 6 }}>
                  {c.direction === "INBOUND" ? "Inbound" : "Outbound"}
                </Badge>
                {c.channel} · {c.subject || (["SMS", "WHATSAPP"].includes(c.channel.toUpperCase()) ? c.body : null) || "—"}
                {c.call_outcome && <Badge variant="gray" style={{ marginLeft: 6 }}>{c.call_outcome.replace(/_/g, " ")}</Badge>}
                {c.delivery_status && <Badge variant="gray" style={{ marginLeft: 6 }}>{c.delivery_status}</Badge>}
              </div>
              <div className="tl-d">
                {formatDateTime(c.occurred_at)}
                {c.to_recipients ? ` · to ${c.to_recipients}` : ""}
                {c.call_duration_seconds != null ? ` · ${Math.round(c.call_duration_seconds / 60)} min` : ""}
              </div>
            </div>
          ))}
          {comms !== null && comms.length === 0 && (
            <div className="t-muted" style={{ fontSize: 13 }}>No activity logged yet.</div>
          )}
        </div>
      </div>
      <LogCallModal
        open={showLogCall}
        lead={lead}
        onClose={() => setShowLogCall(false)}
        onLogged={(c) => setComms((prev) => [c, ...(prev ?? [])])}
        onUpdated={(c) => setComms((prev) => prev?.map((x) => (x.id === c.id ? c : x)) ?? null)}
      />
      <SendEmailModal
        open={showSendEmail}
        lead={lead}
        onClose={() => setShowSendEmail(false)}
        onSent={(c) => setComms((prev) => [c, ...(prev ?? [])])}
      />
      <SendSmsModal
        open={showSendSms}
        lead={lead}
        onClose={() => setShowSendSms(false)}
        onSent={(c) => setComms((prev) => [c, ...(prev ?? [])])}
      />
      <SendWhatsAppModal
        open={showSendWhatsApp}
        lead={lead}
        onClose={() => setShowSendWhatsApp(false)}
        onSent={(c) => setComms((prev) => [c, ...(prev ?? [])])}
      />
      <ActivityDetailModal communication={selected} onClose={() => setSelected(null)} />
    </div>
  );
}

function ActivityDetailModal({
  communication,
  onClose,
}: {
  communication: CommunicationOut | null;
  onClose: () => void;
}) {
  if (!communication) return null;
  const c = communication;
  const isEmail = c.channel.toUpperCase() === "EMAIL";
  const isSms = c.channel.toUpperCase() === "SMS";
  const isWhatsApp = c.channel.toUpperCase() === "WHATSAPP";
  const isCall = !isEmail && !isSms && !isWhatsApp;
  const title = isEmail
    ? (c.direction === "INBOUND" ? "Inbound email" : "Outbound email")
    : isSms
    ? (c.direction === "INBOUND" ? "Inbound SMS" : "Outbound SMS")
    : isWhatsApp
    ? (c.direction === "INBOUND" ? "Inbound WhatsApp" : "Outbound WhatsApp")
    : "Call";
  return (
    <Modal
      open={!!communication}
      onClose={onClose}
      title={title}
      footer={<button className="btn sm" onClick={onClose}>Close</button>}
    >
      <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
        <div className="field">
          <div className="lab">Date/time</div>
          <div className="val">{formatDateTime(c.occurred_at)}</div>
        </div>
        {isEmail && (
          <>
            {c.from_address && (
              <div className="field">
                <div className="lab">From</div>
                <div className="val">{c.from_address}</div>
              </div>
            )}
            {c.to_recipients && (
              <div className="field">
                <div className="lab">To</div>
                <div className="val">{c.to_recipients}</div>
              </div>
            )}
          </>
        )}
        {(isSms || isWhatsApp) && c.to_recipients && (
          <div className="field">
            <div className="lab">To</div>
            <div className="val">{c.to_recipients}</div>
          </div>
        )}
        {isWhatsApp && c.delivery_status && (
          <div className="field">
            <div className="lab">Status</div>
            <div className="val">{c.delivery_status}{c.failure_code ? ` (${c.failure_code})` : ""}</div>
          </div>
        )}
        {isEmail && (
          <div className="field">
            <div className="lab">Subject</div>
            <div className="val">{c.subject || "—"}</div>
          </div>
        )}
        {isEmail && (
          <div className="field">
            <div className="lab">Body</div>
            <div className="val" style={{ whiteSpace: "pre-wrap" }}>{c.body || "—"}</div>
          </div>
        )}
        {(isSms || isWhatsApp) && (
          <div className="field">
            <div className="lab">Message</div>
            <div className="val" style={{ whiteSpace: "pre-wrap" }}>{c.body || "—"}</div>
          </div>
        )}
        {isCall && (
          <>
            <div className="field">
              <div className="lab">Subject</div>
              <div className="val">{c.subject || "—"}</div>
            </div>
            {c.call_outcome && (
              <div className="field">
                <div className="lab">Outcome</div>
                <div className="val">{c.call_outcome.replace(/_/g, " ")}</div>
              </div>
            )}
            {c.call_duration_seconds != null && (
              <div className="field">
                <div className="lab">Duration</div>
                <div className="val">{Math.round(c.call_duration_seconds / 60)} min</div>
              </div>
            )}
            {c.to_recipients && (
              <div className="field">
                <div className="lab">Phone</div>
                <div className="val">{c.to_recipients}</div>
              </div>
            )}
            <div className="field">
              <div className="lab">Notes</div>
              <div className="val" style={{ whiteSpace: "pre-wrap" }}>{c.notes || "—"}</div>
            </div>
          </>
        )}
      </div>
    </Modal>
  );
}

function LogCallModal({
  open,
  lead,
  onClose,
  onLogged,
  onUpdated,
}: {
  open: boolean;
  lead: LeadOut;
  onClose: () => void;
  onLogged: (c: CommunicationOut) => void;
  onUpdated: (c: CommunicationOut) => void;
}) {
  const api = useApi();
  const [outcomes, setOutcomes] = useState<string[]>(FALLBACK_CALL_OUTCOMES);
  const [subject, setSubject] = useState("");
  const [outcome, setOutcome] = useState(FALLBACK_CALL_OUTCOMES[0]);
  const [durationMinutes, setDurationMinutes] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const [prep, setPrep] = useState<CallPrepOut | null>(null);
  const [prepError, setPrepError] = useState<string | null>(null);
  const [isPrepping, startPrepping] = useTransition();

  // --- Dial Pad / Twilio Voice browser calling — additive to everything
  // above. liveCallCommId is set once a real call placed through the Dial
  // Pad has a matching Communication row (found via a short post-call poll,
  // keyed on the Twilio parent Call SID) — from that point on, Outcome/
  // Duration below become Twilio-driven read-only display (the frontend
  // must never invent the final outcome/duration), while Subject/Notes stay
  // freely editable and save onto that SAME row instead of creating a new one.
  const [dialNumber, setDialNumber] = useState("");
  const [callPhase, setCallPhase] = useState<CallPhase>("idle");
  const [callError, setCallError] = useState<string | null>(null);
  const [liveCallCommId, setLiveCallCommId] = useState<string | null>(null);
  const deviceRef = useRef<import("@twilio/voice-sdk").Device | null>(null);
  const activeCallRef = useRef<import("@twilio/voice-sdk").Call | null>(null);

  function teardownDevice() {
    activeCallRef.current = null;
    deviceRef.current?.destroy();
    deviceRef.current = null;
  }

  async function pollForCallCommunication(sid: string) {
    // Tracked locally, not via the liveCallCommId state — this loop's own
    // closure would otherwise keep seeing the stale (null) value from when
    // it started, and call onLogged() a second time on a later iteration
    // instead of onUpdated(), double-inserting the row into the timeline.
    let insertedRowId: string | null = null;
    for (let attempt = 0; attempt < 6; attempt++) {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      try {
        const comms = await listLeadCommunications(api, lead.id);
        const row = comms.find((c) => c.provider_message_id === sid);
        if (row) {
          setLiveCallCommId(row.id);
          if (row.call_outcome) setOutcome(row.call_outcome);
          if (row.call_duration_seconds != null) setDurationMinutes(String(Math.round(row.call_duration_seconds / 60)));
          if (insertedRowId == null) {
            onLogged(row);
            insertedRowId = row.id;
          } else {
            onUpdated(row);
          }
          if (row.delivery_status && ["completed", "busy", "no-answer", "failed", "canceled"].includes(row.delivery_status)) {
            return;
          }
        }
      } catch {
        // keep retrying — a transient fetch failure shouldn't stop the poll
      }
    }
  }

  async function startCall() {
    const number = dialNumber.trim();
    if (!number) {
      setCallError("Enter a phone number to call.");
      return;
    }
    setCallError(null);
    setLiveCallCommId(null);
    setCallPhase("requesting-token");
    try {
      const { Device } = await import("@twilio/voice-sdk");
      const { token } = await getLeadVoiceToken(api, lead.id);
      const device = new Device(token);
      deviceRef.current = device;
      device.on("error", (err: { message?: string }) => {
        setCallError(err.message || "The calling device reported an error.");
        setCallPhase("failed");
        teardownDevice();
      });

      setCallPhase("connecting");
      const call = await device.connect({ params: { To: number, LeadId: lead.id } });
      activeCallRef.current = call;

      call.on("ringing", () => setCallPhase("ringing"));
      call.on("accept", () => setCallPhase("in-progress"));
      call.on("disconnect", () => {
        setCallPhase("wrapping-up");
        const sid = call.outboundConnectionId;
        teardownDevice();
        if (sid) void pollForCallCommunication(sid).then(() => setCallPhase("ended"));
        else setCallPhase("ended");
      });
      call.on("cancel", () => {
        setCallPhase("ended");
        teardownDevice();
      });
      call.on("reject", () => {
        setCallPhase("ended");
        teardownDevice();
      });
      call.on("error", (err: { message?: string }) => {
        setCallError(err.message || "The call failed.");
        setCallPhase("failed");
        teardownDevice();
      });
    } catch (err) {
      setCallError(err instanceof ApiError ? err.message : "Could not start the call.");
      setCallPhase("failed");
      teardownDevice();
    }
  }

  function hangUp() {
    activeCallRef.current?.disconnect();
  }

  function draftPrep() {
    setPrepError(null);
    startPrepping(async () => {
      try {
        const result = await generateCallPrep(api, lead.id);
        setPrep(result);
        setSubject((current) => current || result.opening_line);
      } catch (err) {
        setPrep(null);
        setPrepError(err instanceof ApiError ? err.message : "Failed to generate call prep.");
      }
    });
  }

  useEffect(() => {
    if (!open) return;
    setSubject("");
    setDurationMinutes("");
    setNotes("");
    setError(null);
    setPrep(null);
    setPrepError(null);
    setDialNumber(lead.contact_phone || lead.mobile_phone || "");
    setCallPhase("idle");
    setCallError(null);
    setLiveCallCommId(null);
    listLookups(api, "call_disposition")
      .then((rows: LookupOut[]) => {
        const codes = rows.map((r) => r.code).filter((c): c is string => c != null);
        if (codes.length) {
          setOutcomes(codes);
          setOutcome(codes[0]);
        } else {
          setOutcomes(FALLBACK_CALL_OUTCOMES);
          setOutcome(FALLBACK_CALL_OUTCOMES[0]);
        }
      })
      .catch(() => {
        setOutcomes(FALLBACK_CALL_OUTCOMES);
        setOutcome(FALLBACK_CALL_OUTCOMES[0]);
      });
    draftPrep();
    return () => teardownDevice();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, api, lead.id]);

  function submit() {
    startTransition(async () => {
      try {
        const created = await addLeadCommunication(api, lead.id, {
          direction: "OUTBOUND",
          channel: "Call",
          subject: subject.trim() || `Call with ${lead.first_name ?? ""} ${lead.last_name}`.trim(),
          to_recipients: lead.contact_phone ?? lead.mobile_phone ?? null,
          occurred_at: new Date().toISOString(),
          call_outcome: outcome,
          call_duration_seconds: durationMinutes.trim() ? Number(durationMinutes) * 60 : null,
          notes: notes.trim() || null,
        });
        onLogged(created);
        onClose();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to log call.");
      }
    });
  }

  function saveNotes() {
    if (!liveCallCommId) return;
    startTransition(async () => {
      try {
        const updated = await updateCallNotes(api, lead.id, liveCallCommId, {
          subject: subject.trim() || null,
          notes: notes.trim() || null,
        });
        onUpdated(updated);
        onClose();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to save call notes.");
      }
    });
  }

  const callInProgress = callPhase === "requesting-token" || callPhase === "connecting"
    || callPhase === "ringing" || callPhase === "in-progress";

  function handleClose() {
    if (callInProgress) hangUp();
    teardownDevice();
    onClose();
  }

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Log a call"
      footer={
        <>
          <button className="btn sm" onClick={handleClose} disabled={isPending}>Cancel</button>
          <div className="spacer" />
          {liveCallCommId ? (
            <button className="btn primary sm" onClick={saveNotes} disabled={isPending}>
              {isPending ? "Saving…" : "Save notes"}
            </button>
          ) : (
            <button
              className="btn primary sm"
              onClick={submit}
              disabled={isPending || callPhase !== "idle"}
              title={callPhase !== "idle" ? "Waiting for the call record to sync…" : undefined}
            >
              {isPending ? "Logging…" : "Log call"}
            </button>
          )}
        </>
      }
    >
      <div className="fields" style={{ gridTemplateColumns: "1fr 1fr" }}>
        <div className="field" style={{ gridColumn: "1 / -1" }}>
          <div className="lab">Dial Pad</div>
          <Dialpad value={dialNumber} onChange={setDialNumber} disabled={callInProgress} />
          {callPhase !== "idle" && (
            <div className="help" style={{ marginTop: 8 }}>{CALL_PHASE_LABEL[callPhase]}</div>
          )}
          {callError && <div className="help err">{callError}</div>}
          <div style={{ marginTop: 8 }}>
            {callInProgress ? (
              <button type="button" className="btn sm" onClick={hangUp}>End call</button>
            ) : (
              <button type="button" className="btn primary sm" onClick={startCall}>📞 Call</button>
            )}
          </div>
        </div>
        <div className="field" style={{ gridColumn: "1 / -1" }}>
          <div className="lab">
            Call prep
            <button
              type="button"
              className="btn sm"
              style={{ marginLeft: 8 }}
              onClick={draftPrep}
              disabled={isPrepping}
            >
              {isPrepping ? "Drafting…" : prep ? "Regenerate" : "Draft with AI"}
            </button>
          </div>
          {prepError && <div className="help err">{prepError}</div>}
          {prep && (
            <div className="help" style={{ marginTop: 4 }}>
              {prep.matched_products.length > 0 && (
                <div><b>Matched product{prep.matched_products.length === 1 ? "" : "s"}:</b> {prep.matched_products.join(", ")}</div>
              )}
              <div><b>Opening:</b> {prep.opening_line}</div>
              {prep.talking_points.length > 0 && (
                <div style={{ marginTop: 6 }}>
                  <b>Talking points:</b>
                  <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                    {prep.talking_points.map((point, i) => <li key={i}>{point}</li>)}
                  </ul>
                </div>
              )}
              {prep.likely_objections.length > 0 && (
                <div style={{ marginTop: 6 }}>
                  <b>Likely objections:</b>
                  <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                    {prep.likely_objections.map((point, i) => <li key={i}>{point}</li>)}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
        <div className="field" style={{ gridColumn: "1 / -1" }}>
          <div className="lab">Subject</div>
          <input
            className="inp"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder={`Call with ${lead.first_name ?? ""} ${lead.last_name}`.trim()}
            autoFocus
          />
        </div>
        <div className="field">
          <div className="lab">Outcome{liveCallCommId ? " (from Twilio)" : ""}</div>
          {liveCallCommId ? (
            <div className="val">{outcome ? outcome.replace(/_/g, " ") : "Pending…"}</div>
          ) : (
            <select className="inp" value={outcome} onChange={(e) => setOutcome(e.target.value)}>
              {outcomes.map((o) => (
                <option key={o} value={o}>{o.replace(/_/g, " ")}</option>
              ))}
            </select>
          )}
        </div>
        <div className="field">
          <div className="lab">Duration (minutes){liveCallCommId ? " (from Twilio)" : ""}</div>
          {liveCallCommId ? (
            <div className="val">{durationMinutes || "Pending…"}</div>
          ) : (
            <input className="inp" type="number" min={0} value={durationMinutes} onChange={(e) => setDurationMinutes(e.target.value)} />
          )}
        </div>
        <div className="field" style={{ gridColumn: "1 / -1" }}>
          <div className="lab">Notes</div>
          <textarea className="inp" rows={4} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="What was discussed…" />
        </div>
        {error && <div className="help err" style={{ gridColumn: "1 / -1" }}>{error}</div>}
      </div>
    </Modal>
  );
}

function SendEmailModal({
  open,
  lead,
  onClose,
  onSent,
}: {
  open: boolean;
  lead: LeadOut;
  onClose: () => void;
  onSent: (c: CommunicationOut) => void;
}) {
  const api = useApi();
  const [toAddress, setToAddress] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const [draft, setDraft] = useState<EmailDraftOut | null>(null);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [isDrafting, startDrafting] = useTransition();

  function draftEmail() {
    setDraftError(null);
    startDrafting(async () => {
      try {
        const result = await generateEmailDraft(api, lead.id);
        setDraft(result);
        setSubject(result.subject);
        setBody(result.body);
      } catch (err) {
        setDraft(null);
        setDraftError(err instanceof ApiError ? err.message : "Failed to generate a draft.");
      }
    });
  }

  useEffect(() => {
    if (!open) return;
    setToAddress(lead.contact_email ?? "");
    setSubject("");
    setBody("");
    setError(null);
    setDraft(null);
    setDraftError(null);
    draftEmail();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, lead.id, lead.contact_email]);

  function submit() {
    if (!toAddress.trim()) {
      setError("A recipient email is required.");
      return;
    }
    if (!subject.trim() || !body.trim()) {
      setError("Subject and body are required.");
      return;
    }
    startTransition(async () => {
      try {
        const sent = await sendLeadEmail(api, lead.id, {
          to_address: toAddress.trim(),
          subject: subject.trim(),
          body: body.trim(),
        });
        onSent(sent);
        onClose();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to send email.");
      }
    });
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Send email"
      footer={
        <>
          <button className="btn sm" onClick={onClose} disabled={isPending}>Cancel</button>
          <div className="spacer" />
          <button className="btn primary sm" onClick={submit} disabled={isPending}>{isPending ? "Sending…" : "Send"}</button>
        </>
      }
    >
      <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
        <div className="field">
          <div className="lab">To <span className="req">*</span></div>
          <input className="inp" type="email" value={toAddress} onChange={(e) => setToAddress(e.target.value)} autoFocus />
        </div>
        <div className="field">
          <div className="lab">
            Subject <span className="req">*</span>
            <button
              type="button"
              className="btn sm"
              style={{ marginLeft: 8 }}
              onClick={draftEmail}
              disabled={isDrafting}
            >
              {isDrafting ? "Drafting…" : draft ? "Regenerate" : "Draft with AI"}
            </button>
          </div>
          <input className="inp" value={subject} onChange={(e) => setSubject(e.target.value)} />
        </div>
        {draftError && <div className="help err">{draftError}</div>}
        {draft && (
          <div className="help">
            Drafted by Tachyon Aura
            {draft.grounded_in_replies > 0
              ? ` · grounded in ${draft.grounded_in_replies} past-replied email${draft.grounded_in_replies === 1 ? "" : "s"} in this industry`
              : ""}
            {draft.matched_products.length > 0
              ? ` · matched to ${draft.matched_products.join(", ")}`
              : ""}
            . Edit freely before sending.
          </div>
        )}
        <div className="field">
          <div className="lab">Body <span className="req">*</span></div>
          <textarea className="inp" rows={6} value={body} onChange={(e) => setBody(e.target.value)} />
        </div>
        {error && <div className="help err">{error}</div>}
      </div>
    </Modal>
  );
}

function SendSmsModal({
  open,
  lead,
  onClose,
  onSent,
}: {
  open: boolean;
  lead: LeadOut;
  onClose: () => void;
  onSent: (c: CommunicationOut) => void;
}) {
  const api = useApi();
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const toNumber = lead.contact_phone || lead.mobile_phone || "";
  const trimmed = message.trim();
  const overLimit = message.length > SMS_MAX_LENGTH;
  const canSend = trimmed.length > 0 && !overLimit && !!toNumber;

  useEffect(() => {
    if (!open) return;
    setMessage("");
    setError(null);
  }, [open, lead.id]);

  function submit() {
    if (!toNumber) {
      setError("This lead has no phone number on file.");
      return;
    }
    if (!trimmed) {
      setError("A message is required.");
      return;
    }
    if (overLimit) {
      setError(`Message is over the ${SMS_MAX_LENGTH}-character limit.`);
      return;
    }
    startTransition(async () => {
      try {
        const sent = await sendLeadSms(api, lead.id, { message: trimmed });
        onSent(sent);
        onClose();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to send SMS.");
      }
    });
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Send SMS"
      footer={
        <>
          <button className="btn sm" onClick={onClose} disabled={isPending}>Cancel</button>
          <div className="spacer" />
          <button className="btn primary sm" onClick={submit} disabled={isPending || !canSend}>
            {isPending ? "Sending…" : "Send"}
          </button>
        </>
      }
    >
      <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
        <div className="field">
          <div className="lab">To</div>
          <div className="val">{toNumber || "No phone on file"}</div>
        </div>
        <div className="field">
          <div className="lab">Message <span className="req">*</span></div>
          <textarea
            className="inp"
            rows={5}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            maxLength={SMS_MAX_LENGTH + 200}
            autoFocus
          />
          <div className={overLimit ? "help err" : "help"}>
            {message.length} / {SMS_MAX_LENGTH}
          </div>
        </div>
        {error && <div className="help err">{error}</div>}
      </div>
    </Modal>
  );
}

function SendWhatsAppModal({
  open,
  lead,
  onClose,
  onSent,
}: {
  open: boolean;
  lead: LeadOut;
  onClose: () => void;
  onSent: (c: CommunicationOut) => void;
}) {
  const api = useApi();
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const toNumber = lead.whatsapp_number || lead.contact_phone || lead.mobile_phone || "";
  const trimmed = message.trim();
  const overLimit = message.length > WHATSAPP_MAX_LENGTH;
  const canSend = trimmed.length > 0 && !overLimit && !!toNumber;

  useEffect(() => {
    if (!open) return;
    setMessage("");
    setError(null);
  }, [open, lead.id]);

  function submit() {
    if (!toNumber) {
      setError("This lead has no WhatsApp number, contact phone, or mobile phone on file.");
      return;
    }
    if (!trimmed) {
      setError("A message is required.");
      return;
    }
    if (overLimit) {
      setError(`Message is over the ${WHATSAPP_MAX_LENGTH}-character limit.`);
      return;
    }
    startTransition(async () => {
      try {
        const sent = await sendLeadWhatsApp(api, lead.id, { body: trimmed });
        onSent(sent);
        onClose();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to send WhatsApp message.");
      }
    });
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="WhatsApp"
      footer={
        <>
          <button className="btn sm" onClick={onClose} disabled={isPending}>Cancel</button>
          <div className="spacer" />
          <button className="btn primary sm" onClick={submit} disabled={isPending || !canSend}>
            {isPending ? "Sending…" : "Send"}
          </button>
        </>
      }
    >
      <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
        <div className="field">
          <div className="lab">Lead</div>
          <div className="val">{`${lead.first_name ?? ""} ${lead.last_name ?? ""}`.trim() || lead.company_name}</div>
        </div>
        <div className="field">
          <div className="lab">WhatsApp</div>
          <div className="val">{toNumber || "No WhatsApp number, contact phone, or mobile phone on file"}</div>
        </div>
        <div className="field">
          <div className="lab">Message <span className="req">*</span></div>
          <textarea
            className="inp"
            rows={5}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            maxLength={WHATSAPP_MAX_LENGTH + 200}
            placeholder="Type your message…"
            autoFocus
          />
          <div className={overLimit ? "help err" : "help"}>
            {message.length} / {WHATSAPP_MAX_LENGTH}
          </div>
        </div>
        {error && <div className="help err">{error}</div>}
      </div>
    </Modal>
  );
}
