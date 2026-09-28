"use client";

import { useState, useTransition } from "react";
import Modal from "../Modal";
import { ApiError, useApi } from "@/lib/api/client";
import { convertLead, type LeadOut } from "@/lib/api/crm";

export default function ConvertLeadModal({
  lead,
  onClose,
  onConverted,
}: {
  lead: LeadOut | null;
  onClose: () => void;
  onConverted: (lead: LeadOut) => void;
}) {
  const api = useApi();
  const [opportunityName, setOpportunityName] = useState("");
  const [estimatedValue, setEstimatedValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const open = lead !== null;

  function close() {
    setOpportunityName("");
    setEstimatedValue("");
    setError(null);
    onClose();
  }

  function submit() {
    if (!lead) return;
    if (!opportunityName.trim()) {
      setError("Opportunity name is required.");
      return;
    }
    startTransition(async () => {
      try {
        const converted = await convertLead(api, lead.id, {
          opportunity_name: opportunityName.trim(),
          estimated_value: estimatedValue.trim() ? Number(estimatedValue) : null,
        });
        onConverted(converted);
        close();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to convert lead.");
      }
    });
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title="Convert lead"
      footer={
        <>
          <button className="btn sm" onClick={close} disabled={isPending}>Cancel</button>
          <div className="spacer" />
          <button className="btn primary sm" onClick={submit} disabled={isPending}>
            {isPending ? "Converting…" : "Convert"}
          </button>
        </>
      }
    >
      {lead && (
        <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
          <div className="help" style={{ marginBottom: 4 }}>
            Creates an Account (<b>{lead.company_name}</b>), a primary Contact (
            <b>{[lead.first_name, lead.last_name].filter(Boolean).join(" ")}</b>),
            and this Opportunity together, in one action. This can&apos;t be undone.
          </div>
          <div className="field">
            <div className="lab">Opportunity name <span className="req">*</span></div>
            <input
              className="inp"
              value={opportunityName}
              onChange={(e) => setOpportunityName(e.target.value)}
              autoFocus
            />
          </div>
          <div className="field">
            <div className="lab">Estimated value</div>
            <input
              className="inp"
              type="number"
              value={estimatedValue}
              onChange={(e) => setEstimatedValue(e.target.value)}
            />
          </div>
          {error && <div className="help err">{error}</div>}
        </div>
      )}
    </Modal>
  );
}
