"use client";

import { useState, useTransition } from "react";
import Modal from "../Modal";
import { ApiError, useApi } from "@/lib/api/client";
import { sendCampaignEmail, type CampaignOut, type CampaignSendResult } from "@/lib/api/crm";

export default function SendCampaignEmailModal({
  campaign,
  onClose,
  onSent,
}: {
  campaign: CampaignOut | null;
  onClose: () => void;
  onSent: (campaignId: string, result: CampaignSendResult) => void;
}) {
  const api = useApi();
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  // Set once the send completes — the modal then shows a per-outcome summary
  // instead of just closing, same pattern as NewEmployeeModal's confirmation.
  const [result, setResult] = useState<CampaignSendResult | null>(null);

  function reset() {
    setSubject("");
    setBody("");
    setError(null);
    setResult(null);
  }

  function close() {
    reset();
    onClose();
  }

  function submit() {
    if (!campaign) return;
    if (!subject.trim() || !body.trim()) {
      setError("Subject and body are required.");
      return;
    }
    startTransition(async () => {
      try {
        const sendResult = await sendCampaignEmail(api, campaign.id, {
          subject: subject.trim(),
          body: body.trim(),
        });
        setResult(sendResult);
        onSent(campaign.id, sendResult);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to send campaign email.");
      }
    });
  }

  if (result) {
    return (
      <Modal
        open={campaign !== null}
        onClose={close}
        title={`Sent — ${campaign?.name}`}
        footer={<button className="btn primary sm" onClick={close} style={{ marginLeft: "auto" }}>Done</button>}
      >
        <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
          <div className="help" style={{ color: "var(--green)" }}>
            Sent to {result.sent} of {result.total_targeted} targeted lead{result.total_targeted === 1 ? "" : "s"}.
          </div>
          {result.skipped_no_email > 0 && (
            <div className="help">{result.skipped_no_email} skipped — no email on file.</div>
          )}
          {result.skipped_opted_out > 0 && (
            <div className="help">{result.skipped_opted_out} skipped — opted out of email.</div>
          )}
          {result.failed > 0 && (
            <div className="help err">{result.failed} failed to send — try again later.</div>
          )}
        </div>
      </Modal>
    );
  }

  return (
    <Modal
      open={campaign !== null}
      onClose={close}
      title={campaign ? `Send email — ${campaign.name}` : "Send campaign email"}
      footer={
        <>
          <button className="btn sm" onClick={close} disabled={isPending}>Cancel</button>
          <div className="spacer" />
          <button className="btn primary sm" onClick={submit} disabled={isPending}>
            {isPending ? "Sending…" : "Send"}
          </button>
        </>
      }
    >
      <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
        <div className="help">
          Sends to every lead in this campaign with an email on file who hasn&apos;t opted out. Sales reps only
          reach leads they own; Account Execs and Admins reach everyone in the campaign.
        </div>
        <div className="field">
          <div className="lab">Subject <span className="req">*</span></div>
          <input className="inp" value={subject} onChange={(e) => setSubject(e.target.value)} autoFocus />
        </div>
        <div className="field">
          <div className="lab">Body <span className="req">*</span></div>
          <textarea className="inp" rows={8} value={body} onChange={(e) => setBody(e.target.value)} />
        </div>
        {error && <div className="help err">{error}</div>}
      </div>
    </Modal>
  );
}
