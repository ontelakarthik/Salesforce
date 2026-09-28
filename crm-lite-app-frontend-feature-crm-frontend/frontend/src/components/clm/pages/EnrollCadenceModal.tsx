"use client";

import { useEffect, useState, useTransition } from "react";
import Modal from "../Modal";
import { ApiError, useApi } from "@/lib/api/client";
import { enrollLeadInCadence, listCadenceTemplates, type CadenceTemplateOut } from "@/lib/api/cadence";

export default function EnrollCadenceModal({
  open,
  leadId,
  onClose,
  onEnrolled,
}: {
  open: boolean;
  leadId: string;
  onClose: () => void;
  onEnrolled: () => void;
}) {
  const api = useApi();
  const [templates, setTemplates] = useState<CadenceTemplateOut[] | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    if (!open) return;
    setSelectedId("");
    setError(null);
    setTemplates(null);
    listCadenceTemplates(api)
      .then((rows) => setTemplates(rows.filter((t) => t.is_active)))
      .catch(() => setTemplates([]));
  }, [open, api]);

  function close() {
    setError(null);
    onClose();
  }

  function submit() {
    if (!selectedId) {
      setError("Choose a cadence template.");
      return;
    }
    startTransition(async () => {
      try {
        await enrollLeadInCadence(api, leadId, selectedId);
        onEnrolled();
        close();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to enroll lead in cadence.");
      }
    });
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title="Enroll in cadence"
      footer={
        <>
          <button className="btn sm" onClick={close} disabled={isPending}>Cancel</button>
          <div className="spacer" />
          <button className="btn primary sm" onClick={submit} disabled={isPending || !templates?.length}>
            {isPending ? "Enrolling…" : "Enroll"}
          </button>
        </>
      }
    >
      {templates === null ? (
        <div className="t-muted">Loading templates…</div>
      ) : templates.length === 0 ? (
        <div className="t-muted">No active cadence templates yet — ask an admin to create one.</div>
      ) : (
        <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
          {templates.map((t) => (
            <label
              key={t.id}
              className="field"
              style={{
                border: "1px solid var(--border)", borderRadius: 8, padding: 12, cursor: "pointer",
                display: "flex", gap: 10, alignItems: "flex-start",
                background: selectedId === t.id ? "var(--primary-soft)" : "var(--surface)",
              }}
            >
              <input
                type="radio"
                name="cadence-template"
                checked={selectedId === t.id}
                onChange={() => setSelectedId(t.id)}
                style={{ marginTop: 3 }}
              />
              <div>
                <div className="t-strong">{t.name}</div>
                {t.description && <div className="t-muted" style={{ fontSize: 12.5, marginTop: 2 }}>{t.description}</div>}
                <div className="t-muted" style={{ fontSize: 11.5, marginTop: 4 }}>{t.steps.length} step{t.steps.length === 1 ? "" : "s"}</div>
              </div>
            </label>
          ))}
        </div>
      )}
      {error && <div className="help err" style={{ marginTop: 10 }}>{error}</div>}
    </Modal>
  );
}
