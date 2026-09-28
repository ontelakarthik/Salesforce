"use client";

import { useState, useTransition } from "react";
import Spinner from "../Spinner";
import { ApiError, useApi } from "@/lib/api/client";
import { useEmployeeDirectory } from "@/lib/api/identity";
import {
  RECORD_SHARE_ACCESS_LEVELS,
  SHAREABLE_OBJECTS,
  createRecordShare,
  deleteRecordShare,
  listRecordShares,
  type RecordShareOut,
} from "@/lib/api/recordShares";

const OBJECT_LABELS: Record<string, string> = {
  LEAD: "Lead",
  ACCOUNT: "Account",
  CONTACT: "Contact",
  OPPORTUNITY: "Opportunity",
  CAMPAIGN: "Campaign",
};

/** Salesforce-style user-based Record Sharing — grants a specific employee
 * READ or EDIT on one record, on top of whatever Organization-Wide Defaults
 * and ownership already provide. No role/team/group targeting by design.
 * Backend enforces that the caller can already EDIT the target record
 * before letting them grant a share on it (see crm_service.
 * create_record_share()) — this page can't bypass that. */
export default function RecordShares() {
  const api = useApi();
  const { label, entries } = useEmployeeDirectory();
  const [objectName, setObjectName] = useState<string>(SHAREABLE_OBJECTS[0]);
  const [recordId, setRecordId] = useState("");
  const [shares, setShares] = useState<RecordShareOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, startLoading] = useTransition();

  const [newEmployeeId, setNewEmployeeId] = useState("");
  const [newAccessLevel, setNewAccessLevel] = useState<string>(RECORD_SHARE_ACCESS_LEVELS[0]);
  const [isSaving, startSaving] = useTransition();

  function load() {
    if (!recordId.trim()) return;
    setError(null);
    startLoading(async () => {
      try {
        setShares(await listRecordShares(api, objectName, recordId.trim()));
      } catch (err) {
        setShares(null);
        setError(err instanceof ApiError ? err.message : "Failed to load shares for this record.");
      }
    });
  }

  function addShare() {
    if (!recordId.trim() || !newEmployeeId) return;
    setError(null);
    startSaving(async () => {
      try {
        await createRecordShare(api, {
          object_name: objectName,
          record_id: recordId.trim(),
          shared_with_employee_id: newEmployeeId,
          access_level: newAccessLevel,
        });
        setNewEmployeeId("");
        load();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to create the share.");
      }
    });
  }

  function revoke(shareId: string) {
    if (!window.confirm("Revoke this share?")) return;
    setError(null);
    startSaving(async () => {
      try {
        await deleteRecordShare(api, shareId);
        load();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to revoke the share.");
      }
    });
  }

  return (
    <section className="page active">
      <div className="pagehead">
        <div>
          <h1 title="Grants ONE specific employee READ or EDIT on ONE record, on top of Organization-Wide Defaults and ownership. Never reduces access; never grants Delete.">
            Record Sharing
          </h1>
          <div className="sub">Look up a record, then add or revoke a user-based sharing grant.</div>
        </div>
      </div>

      {error && <div className="help err" style={{ margin: "12px 0" }}>{error}</div>}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-pad">
          <div className="fields" style={{ gridTemplateColumns: "1fr 1fr auto" }}>
            <div className="field">
              <div className="lab">Object</div>
              <select className="inp" value={objectName} onChange={(e) => { setObjectName(e.target.value); setShares(null); }}>
                {SHAREABLE_OBJECTS.map((name) => (
                  <option key={name} value={name}>{OBJECT_LABELS[name]}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <div className="lab">Record id</div>
              <input
                className="inp"
                placeholder={objectName === "ACCOUNT" ? "e.g. ACC-00042" : objectName === "OPPORTUNITY" ? "e.g. OPP-00031" : "UUID"}
                value={recordId}
                onChange={(e) => { setRecordId(e.target.value); setShares(null); }}
              />
            </div>
            <div className="field" style={{ alignSelf: "end" }}>
              <button className="btn primary sm" onClick={load} disabled={!recordId.trim() || isLoading}>
                {isLoading ? "Loading…" : "Look up"}
              </button>
            </div>
          </div>
        </div>
      </div>

      {isLoading && <div className="card card-pad loading-inline"><Spinner /> Loading shares…</div>}

      {shares !== null && !isLoading && (
        <div className="card">
          <div className="card-head"><h3>Shares on this record</h3></div>
          <table>
            <thead>
              <tr><th>Shared with</th><th>Access</th><th>Granted</th><th></th></tr>
            </thead>
            <tbody>
              {shares.map((s) => (
                <tr key={s.id}>
                  <td>{label(s.shared_with_employee_id)}</td>
                  <td>{s.access_level}</td>
                  <td className="t-muted">{new Date(s.granted_at).toLocaleDateString()}</td>
                  <td style={{ textAlign: "right" }}>
                    <button className="btn sm" disabled={isSaving} onClick={() => revoke(s.id)}>Revoke</button>
                  </td>
                </tr>
              ))}
              {shares.length === 0 && (
                <tr><td colSpan={4} className="empty-hint">No shares on this record yet.</td></tr>
              )}
            </tbody>
          </table>
          <div className="card-pad" style={{ borderTop: "1px solid var(--border)" }}>
            <div className="fields" style={{ gridTemplateColumns: "1fr auto auto" }}>
              <div className="field">
                <div className="lab">Share with</div>
                <select className="inp" value={newEmployeeId} onChange={(e) => setNewEmployeeId(e.target.value)}>
                  <option value="">Select an employee…</option>
                  {entries.map((e) => (
                    <option key={e.id} value={e.id}>{e.full_name}</option>
                  ))}
                </select>
              </div>
              <div className="field">
                <div className="lab">Access</div>
                <select className="inp" value={newAccessLevel} onChange={(e) => setNewAccessLevel(e.target.value)}>
                  {RECORD_SHARE_ACCESS_LEVELS.map((lvl) => (
                    <option key={lvl} value={lvl}>{lvl}</option>
                  ))}
                </select>
              </div>
              <div className="field" style={{ alignSelf: "end" }}>
                <button className="btn primary sm" onClick={addShare} disabled={!newEmployeeId || isSaving}>
                  {isSaving ? "Saving…" : "Add share"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
