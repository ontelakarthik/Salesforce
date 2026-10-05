"use client";

import { useEffect, useState } from "react";
import Spinner from "../Spinner";
import { ApiError, useApi } from "@/lib/api/client";
import {
  OWD_ACCESS_LEVELS,
  OWD_OBJECTS,
  getOrgWideDefaults,
  saveOrgWideDefaults,
  type OwdAccessLevel,
} from "@/lib/api/orgWideDefaults";

const OBJECT_LABELS: Record<string, string> = {
  LEAD: "Lead",
  ACCOUNT: "Account",
  CONTACT: "Contact",
  OPPORTUNITY: "Opportunity",
  CAMPAIGN: "Campaign",
};

const LEVEL_LABELS: Record<OwdAccessLevel, string> = {
  PRIVATE: "Private",
  PUBLIC_READ_ONLY: "Public Read Only",
  PUBLIC_READ_WRITE: "Public Read/Write",
};

/** Salesforce-style Organization-Wide Defaults — the baseline record access
 * a non-owner gets before ownership/sharing/records.see_all widen it
 * further. See services/record_access_service.py on the backend; this page
 * is real config, not a "viewing as" simulation — org_wide_defaults.write
 * is enforced server-side on every GET/PUT this page makes. */
export default function OrgWideDefaults() {
  const api = useApi();
  const [defaults, setDefaults] = useState<Record<string, string> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  function load() {
    setDefaults(null);
    setError(null);
    getOrgWideDefaults(api)
      .then((res) => setDefaults(res.defaults))
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Failed to load Organization-Wide Defaults.");
      });
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: fetch/reset state when inputs change
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);

  function change(objectName: string, level: string) {
    setDefaults((prev) => (prev ? { ...prev, [objectName]: level } : prev));
    setSaved(false);
  }

  function save() {
    if (!defaults) return;
    setIsSaving(true);
    setError(null);
    saveOrgWideDefaults(api, defaults)
      .then((res) => {
        setDefaults(res.defaults);
        setSaved(true);
      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Failed to save Organization-Wide Defaults.");
      })
      .finally(() => setIsSaving(false));
  }

  return (
    <section className="page active">
      <div className="pagehead">
        <div>
          <h1 title="The baseline record access a user who is NOT the owner gets, before Sharing Rules or records.see_all widen it further. Private: owner (+ explicit shares) only. Public Read Only: everyone can read, only the owner/a share/records.see_all can edit. Public Read/Write: everyone can read and edit.">
            Organization-Wide Defaults
          </h1>
          <div className="sub">Set the baseline access level for each object — Sharing Rules can only add access on top of this, never take it away.</div>
        </div>
      </div>

      {error && <div className="help err" style={{ margin: "12px 0" }}>{error}</div>}

      {defaults === null ? (
        <div className="card card-pad loading-inline"><Spinner /> Loading…</div>
      ) : (
        <div className="card">
          {saved && <div className="help" style={{ margin: "12px 16px 0", color: "var(--green)" }}>Saved.</div>}
          <div className="card-pad" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {OWD_OBJECTS.map((objectName) => (
              <div key={objectName} className="field" style={{ maxWidth: 360 }}>
                <div className="lab">{OBJECT_LABELS[objectName]}</div>
                <select
                  className="inp"
                  value={defaults[objectName] ?? "PRIVATE"}
                  onChange={(e) => change(objectName, e.target.value)}
                >
                  {OWD_ACCESS_LEVELS.map((level) => (
                    <option key={level} value={level}>{LEVEL_LABELS[level]}</option>
                  ))}
                </select>
              </div>
            ))}
          </div>
          <div className="card-pad" style={{ borderTop: "1px solid var(--border)" }}>
            <button className="btn primary sm" onClick={save} disabled={isSaving}>
              {isSaving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
