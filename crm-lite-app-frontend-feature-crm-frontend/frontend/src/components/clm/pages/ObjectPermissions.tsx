"use client";

import { useEffect, useState } from "react";
import Spinner from "../Spinner";
import { Icon } from "../icons";
import { ApiError, useApi } from "@/lib/api/client";
import { listCapabilities, listProfiles, type ProfileOut } from "@/lib/api/profiles";
import { getProfileCapabilities, saveProfileCapabilities } from "@/lib/api/profiles";

type ObjectName = "LEAD" | "ACCOUNT" | "OPPORTUNITY";

const OBJECTS: { value: ObjectName; label: string; icon: "userCircle" | "building" | "trendingUp" }[] = [
  { value: "LEAD", label: "Lead", icon: "userCircle" },
  { value: "ACCOUNT", label: "Account", icon: "building" },
  { value: "OPPORTUNITY", label: "Opportunity", icon: "trendingUp" },
];

/** Which capability keys belong to each object's Create/Read/Edit/Delete/
 * View All screen — an explicit allowlist, not a string-prefix match, since
 * e.g. "leads.convert"/"leads.flag_hot" also start with "leads." but aren't
 * part of this object's own CRUD (see utils/permissions.py's docstring on
 * the backend for the full reasoning). View All maps every object to the
 * SAME shared records.see_all capability — there's no per-object row-scoping
 * today, so this is one control shown three times, not three real ones. */
const OBJECT_CAPABILITIES: Record<ObjectName, { key: string; label: string }[]> = {
  LEAD: [
    { key: "leads.create", label: "Create" },
    { key: "leads.read", label: "Read" },
    { key: "leads.edit", label: "Edit" },
    { key: "leads.delete", label: "Delete" },
    { key: "records.see_all", label: "View All" },
  ],
  ACCOUNT: [
    { key: "accounts.create", label: "Create" },
    { key: "accounts.read", label: "Read" },
    { key: "accounts.edit", label: "Edit" },
    { key: "accounts.delete", label: "Delete" },
    { key: "records.see_all", label: "View All" },
  ],
  OPPORTUNITY: [
    { key: "opportunities.create", label: "Create" },
    { key: "opportunities.read", label: "Read" },
    { key: "opportunities.edit", label: "Edit" },
    { key: "opportunities.delete", label: "Delete" },
    { key: "records.see_all", label: "View All" },
  ],
};

/** Salesforce's real Object Permissions flow, same drill-down shape as the
 * Field Permissions page: pick a profile, pick an object, check Create/
 * Read/Edit/Delete/View-All. Saving one object's screen fetches the
 * profile's FULL granted-capability set (there's no per-object column on
 * role_capability, it's a flat list), removes this object's allowlisted
 * keys, re-adds the checked ones, and PUTs the merged whole — the profile's
 * other capabilities (admin, platform.read, audit.read, ...) are untouched. */
export default function ObjectPermissions() {
  const api = useApi();
  const [profiles, setProfiles] = useState<ProfileOut[] | null>(null);
  const [selectedProfile, setSelectedProfile] = useState<ProfileOut | null>(null);
  const [selectedObject, setSelectedObject] = useState<ObjectName | null>(null);
  const [granted, setGranted] = useState<Set<string> | null>(null);
  const [descriptions, setDescriptions] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    Promise.all([listProfiles(api), listCapabilities(api)])
      .then(([profileRows, capabilityRows]) => {
        setProfiles(profileRows.filter((p) => p.code !== "ADMIN"));
        setDescriptions(Object.fromEntries(capabilityRows.map((c) => [c.key, c.description])));
      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Failed to load profiles.");
      });
  }, [api]);

  useEffect(() => {
    if (!selectedObject || !selectedProfile) {
      setGranted(null);
      return;
    }
    let cancelled = false;
    setGranted(null);
    setError(null);
    setSaved(false);
    getProfileCapabilities(api, selectedProfile.id)
      .then((res) => {
        if (!cancelled) setGranted(new Set(res.capability_keys));
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Failed to load this profile's capabilities.");
      });
    return () => {
      cancelled = true;
    };
  }, [api, selectedObject, selectedProfile]);

  function toggle(key: string) {
    setGranted((prev) => {
      const next = new Set(prev ?? []);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
    setSaved(false);
  }

  function save() {
    if (!selectedProfile || !selectedObject || granted === null) return;
    setIsSaving(true);
    setError(null);
    saveProfileCapabilities(api, selectedProfile.id, Array.from(granted))
      .then((res) => {
        setGranted(new Set(res.capability_keys));
        setSaved(true);
      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Failed to save object permissions.");
      })
      .finally(() => setIsSaving(false));
  }

  function backToProfiles() {
    setSelectedProfile(null);
    setSelectedObject(null);
  }

  return (
    <section className="page active">
      <div className="pagehead">
        <div>
          <h1 title="Controls whether a profile can access a whole record at all. A profile with no Read here never sees the object in the nav or its pages — different from Field Permissions, which only narrows individual fields on records the profile can already reach.">
            Object Permissions
          </h1>
          <div className="sub">Pick a profile, then an object, to configure Create/Read/Edit/Delete/View All.</div>
        </div>
      </div>

      {error && <div className="help err" style={{ margin: "12px 0" }}>{error}</div>}

      {profiles === null ? (
        <div className="card card-pad loading-inline"><Spinner /> Loading…</div>
      ) : selectedProfile === null ? (
        <div className="card">
          <div className="card-head"><h3>Profiles</h3></div>
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {profiles.map((p) => (
              <li key={p.id} style={{ borderTop: "1px solid var(--border)" }}>
                <button
                  className="btn sm"
                  style={{ width: "100%", justifyContent: "space-between", borderRadius: 0, margin: 0, padding: "12px 16px" }}
                  onClick={() => setSelectedProfile(p)}
                >
                  <span>{p.display_name}</span>
                  <Icon name="chevronRight" />
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : selectedObject === null ? (
        <div className="card">
          <div className="card-head">
            <button className="btn sm" onClick={backToProfiles}>&larr; Profiles</button>
            <h3 style={{ marginLeft: 8 }}>{selectedProfile.display_name}</h3>
          </div>
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {OBJECTS.map((o) => (
              <li key={o.value} style={{ borderTop: "1px solid var(--border)" }}>
                <button
                  className="btn sm"
                  style={{ width: "100%", justifyContent: "space-between", borderRadius: 0, margin: 0, padding: "12px 16px" }}
                  onClick={() => setSelectedObject(o.value)}
                >
                  <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <Icon name={o.icon} />
                    {o.label}
                  </span>
                  <Icon name="chevronRight" />
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="card">
          <div className="card-head">
            <button className="btn sm" onClick={() => setSelectedObject(null)}>&larr; Objects</button>
            <h3 style={{ marginLeft: 8 }}>
              {selectedProfile.display_name} &middot; {OBJECTS.find((o) => o.value === selectedObject)?.label}
            </h3>
          </div>
          {saved && <div className="help" style={{ margin: "0 16px 12px", color: "var(--green)" }}>Saved.</div>}
          {granted === null ? (
            <div className="card-pad loading-inline"><Spinner /> Loading permissions…</div>
          ) : (
            <>
              <div className="card-pad" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {OBJECT_CAPABILITIES[selectedObject].map(({ key, label }) => (
                  <label key={key} style={{ display: "flex", alignItems: "center", gap: 8 }} title={descriptions[key]}>
                    <input type="checkbox" checked={granted.has(key)} onChange={() => toggle(key)} />
                    {label}
                    {key === "records.see_all" && (
                      <span className="t-muted" style={{ fontSize: 12 }}>
                        (shared across all objects — the same setting either way)
                      </span>
                    )}
                  </label>
                ))}
              </div>
              <div className="card-pad" style={{ borderTop: "1px solid var(--border)" }}>
                <button className="btn primary sm" onClick={save} disabled={isSaving}>
                  {isSaving ? "Saving…" : "Save"}
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
