"use client";

import { useEffect, useState } from "react";
import Modal from "../Modal";
import Spinner from "../Spinner";
import { Icon } from "../icons";
import { ApiError, useApi } from "@/lib/api/client";
import {
  createProfile,
  deleteProfile,
  getProfileCapabilities,
  listCapabilities,
  listProfiles,
  saveProfileCapabilities,
  updateProfile,
  type CapabilityEntry,
  type ProfileOut,
} from "@/lib/api/profiles";

/** Groups the ~40 flat capability keys into labeled sections so the
 * checklist reads like Object Permissions' one-object-at-a-time screens
 * instead of one undifferentiated wall of checkboxes. Order here is the
 * display order. Any key the backend registry has that isn't listed below
 * still shows up, under a trailing "Other" section, so a newly-added
 * capability is never silently dropped from the page. */
const CAPABILITY_GROUPS: { label: string; keys: string[] }[] = [
  { label: "Leads", keys: ["leads.read", "leads.create", "leads.edit", "leads.delete", "leads.write", "leads.convert", "leads.flag_hot"] },
  { label: "Accounts", keys: ["accounts.read", "accounts.create", "accounts.edit", "accounts.delete", "accounts.write", "accounts.promote", "accounts.assign"] },
  { label: "Opportunities", keys: ["opportunities.read", "opportunities.create", "opportunities.edit", "opportunities.delete", "opportunities.write"] },
  { label: "Campaigns", keys: ["campaigns.write"] },
  { label: "Lead scoring & cadences", keys: ["lead_scoring_rules.write", "cadence_templates.write", "cadences.enroll"] },
  { label: "Field-level security", keys: ["field_permissions.write"] },
  { label: "Product catalog", keys: ["products.write"] },
  { label: "Projects", keys: ["projects.write"] },
  { label: "Agreements & delivery", keys: ["agreements.write", "agreements.sign", "sow.write"] },
  { label: "Timesheets", keys: ["timesheets.read", "timesheets.submit", "timesheets.approve"] },
  { label: "Dashboards & visibility", keys: ["platform.read", "manager_dashboard.read", "records.see_all"] },
  { label: "Audit", keys: ["audit.read", "audit.see_all"] },
  { label: "Administration", keys: ["admin"] },
];

function groupCapabilities(capabilities: CapabilityEntry[]): { label: string; items: CapabilityEntry[] }[] {
  const byKey = new Map(capabilities.map((c) => [c.key, c]));
  const used = new Set<string>();
  const groups: { label: string; items: CapabilityEntry[] }[] = [];
  for (const { label, keys } of CAPABILITY_GROUPS) {
    const items = keys.map((k) => byKey.get(k)).filter((c): c is CapabilityEntry => c !== undefined);
    items.forEach((c) => used.add(c.key));
    if (items.length > 0) groups.push({ label, items });
  }
  const leftover = capabilities.filter((c) => !used.has(c.key));
  if (leftover.length > 0) groups.push({ label: "Other", items: leftover });
  return groups;
}

/** A real org-chart rendering of the Role Hierarchy — boxes connected by
 * downward lines, one row per depth, same shape as Salesforce's own Setup >
 * Roles diagram (which is what this mirrors). Pure-CSS technique (nested
 * <ul>/<li>, connecting lines drawn with ::before/::after borders) rather
 * than measuring DOM positions for SVG lines — see the <style> block in
 * RoleHierarchyChart below for the whole recipe in one place. */
function OrgChartNode({
  profile,
  allProfiles,
  selectedId,
  onSelect,
}: {
  profile: ProfileOut;
  allProfiles: ProfileOut[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  const children = allProfiles.filter((p) => p.parent_role_id === profile.id);
  return (
    <li>
      <button
        type="button"
        className={`org-node${profile.id === selectedId ? " selected" : ""}`}
        onClick={() => onSelect(profile.id)}
        title={profile.is_system ? "Built-in profile" : "Custom profile"}
      >
        {profile.display_name}
      </button>
      {children.length > 0 && (
        <ul>
          {children.map((c) => (
            <OrgChartNode key={c.id} profile={c} allProfiles={allProfiles} selectedId={selectedId} onSelect={onSelect} />
          ))}
        </ul>
      )}
    </li>
  );
}

function RoleHierarchyChart({
  profiles,
  selectedId,
  onSelect,
}: {
  profiles: ProfileOut[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  const roots = profiles.filter((p) => p.parent_role_id === null);
  return (
    <div style={{ overflowX: "auto" }}>
      <style>{`
        .org-chart, .org-chart ul, .org-chart li { list-style: none; margin: 0; padding: 0; }
        .org-chart { display: flex; justify-content: center; min-width: max-content; }
        .org-chart > ul { display: flex; }
        .org-chart ul { display: flex; padding-top: 28px; }
        .org-chart li { display: flex; flex-direction: column; align-items: center; padding: 0 14px; position: relative; }
        .org-chart li::before, .org-chart li::after {
          content: ""; position: absolute; top: 0; width: 50%; height: 28px; border-top: 2px solid var(--border);
        }
        .org-chart li::before { right: 50%; }
        .org-chart li::after { left: 50%; border-left: 2px solid var(--border); }
        .org-chart li:only-child::before, .org-chart li:only-child::after { border-top: 0 none; height: 0; }
        .org-chart li:only-child { padding-top: 28px; }
        .org-chart li:only-child::before { border-left: 2px solid var(--border); height: 28px; }
        .org-chart li:first-child::before, .org-chart li:last-child::after { border: 0 none; }
        .org-chart li:last-child::before { border-right: 2px solid var(--border); border-radius: 0 6px 0 0; }
        .org-chart li:first-child::after { border-radius: 6px 0 0 0; }
        .org-chart > ul > li { padding-top: 0; }
        .org-chart > ul > li::before, .org-chart > ul > li::after { display: none; }
        .org-node {
          border: 1px solid var(--border); border-radius: 8px; padding: 10px 18px;
          background: var(--surface); font: inherit; font-weight: 600; cursor: pointer;
          white-space: nowrap; box-shadow: var(--shadow-sm);
        }
        .org-node:hover { border-color: var(--border-strong); }
        .org-node.selected { border-color: var(--primary); background: var(--primary-soft); }
      `}</style>
      <div className="org-chart">
        <ul>
          {roots.map((r) => (
            <OrgChartNode key={r.id} profile={r} allProfiles={profiles} selectedId={selectedId} onSelect={onSelect} />
          ))}
        </ul>
      </div>
    </div>
  );
}

export default function Profiles() {
  const api = useApi();
  const [profiles, setProfiles] = useState<ProfileOut[] | null>(null);
  const [capabilities, setCapabilities] = useState<CapabilityEntry[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [granted, setGranted] = useState<Set<string> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [parentError, setParentError] = useState<string | null>(null);
  const [isSavingParent, setIsSavingParent] = useState(false);

  function loadProfiles(selectAfter?: number) {
    setError(null);
    Promise.all([listProfiles(api), listCapabilities(api)])
      .then(([profileRows, capRows]) => {
        setProfiles(profileRows);
        setCapabilities(capRows);
        const target = selectAfter ?? profileRows[0]?.id ?? null;
        setSelectedId(target);
      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Failed to load profiles.");
      });
  }

  useEffect(() => {
    loadProfiles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);

  useEffect(() => {
    if (selectedId === null) {
      setGranted(null);
      return;
    }
    let cancelled = false;
    setGranted(null);
    setSaved(false);
    setSaveError(null);
    getProfileCapabilities(api, selectedId)
      .then((res) => {
        if (!cancelled) setGranted(new Set(res.capability_keys));
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setSaveError(err instanceof ApiError ? err.message : "Failed to load this profile's capabilities.");
      });
    return () => {
      cancelled = true;
    };
  }, [api, selectedId]);

  const selected = profiles?.find((p) => p.id === selectedId) ?? null;

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
    if (selectedId === null || granted === null) return;
    setIsSaving(true);
    setSaveError(null);
    setSaved(false);
    saveProfileCapabilities(api, selectedId, Array.from(granted))
      .then(() => setSaved(true))
      .catch((err: unknown) => {
        setSaveError(err instanceof ApiError ? err.message : "Failed to save capabilities.");
      })
      .finally(() => setIsSaving(false));
  }

  async function remove(profile: ProfileOut) {
    if (!window.confirm(`Delete the profile "${profile.display_name}"? This can't be undone.`)) return;
    try {
      await deleteProfile(api, profile.id);
      loadProfiles();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to delete profile.");
    }
  }

  function setParent(profile: ProfileOut, parentRoleId: number | null) {
    setIsSavingParent(true);
    setParentError(null);
    updateProfile(api, profile.id, { parent_role_id: parentRoleId })
      .then(() => loadProfiles(profile.id))
      .catch((err: unknown) => {
        setParentError(err instanceof ApiError ? err.message : "Failed to update reporting structure.");
      })
      .finally(() => setIsSavingParent(false));
  }

  return (
    <section className="page active">
      <div className="pagehead">
        <div>
          <h1>Profiles</h1>
          <div className="sub">
            Bundles of capabilities an employee is assigned — what they can see and do across the app. A new
            profile starts with nothing granted; check the capabilities it should have below, then Save.
          </div>
        </div>
        <div className="spacer" />
        <button className="btn primary" onClick={() => setShowNew(true)}>
          <Icon name="plus" />
          New profile
        </button>
      </div>

      {error && <div className="help err" style={{ margin: "12px 0" }}>{error}</div>}

      {profiles === null ? (
        <div className="card card-pad loading-inline"><Spinner /> Loading profiles…</div>
      ) : (
        <>
          <div className="card card-pad" style={{ marginBottom: 16 }}>
            <div
              className="card-head"
              title="Holding a profile grants visibility into every Account/Opportunity/Lead owned by anyone holding a profile beneath it here — on top of Records See All, not instead of it. Click a box to select that profile below."
              style={{ marginBottom: 12 }}
            >
              <h3>Role Hierarchy</h3>
            </div>
            <RoleHierarchyChart profiles={profiles} selectedId={selectedId} onSelect={setSelectedId} />
          </div>

          <div className="card">
            {selected === null ? (
              <div className="card-pad t-muted">No profile selected.</div>
            ) : (
              <>
                <div className="card-head">
                  <h3>{selected.display_name}</h3>
                  <div className="spacer" />
                  {selected.code !== "ADMIN" && (
                    <button className="btn sm" onClick={() => remove(selected)}>Delete</button>
                  )}
                </div>
                <div className="card-pad" style={{ borderBottom: "1px solid var(--border)" }}>
                  <div className="field" style={{ maxWidth: 320 }}>
                    <div className="lab">Reports to</div>
                    <select
                      className="inp"
                      value={selected.parent_role_id ?? ""}
                      disabled={isSavingParent}
                      onChange={(e) => setParent(selected, e.target.value ? Number(e.target.value) : null)}
                    >
                      <option value="">None — top level</option>
                      {profiles.filter((p) => p.id !== selected.id).map((p) => (
                        <option key={p.id} value={p.id}>{p.display_name}</option>
                      ))}
                    </select>
                    <div className="help">
                      Whoever holds this profile sees every Account/Opportunity/Lead owned by anyone holding a
                      profile beneath it here — on top of Records See All, not instead of it.
                    </div>
                    {parentError && <div className="help err">{parentError}</div>}
                  </div>
                </div>
                {saveError && <div className="help err" style={{ margin: "0 16px 12px" }}>{saveError}</div>}
                {saved && <div className="help" style={{ margin: "0 16px 12px", color: "var(--green)" }}>Saved.</div>}
                {granted === null ? (
                  <div className="card-pad loading-inline"><Spinner /> Loading capabilities…</div>
                ) : (
                  <>
                    {groupCapabilities(capabilities).map((group) => (
                      <div key={group.label} className="card-pad" style={{ borderTop: "1px solid var(--border)" }}>
                        <div className="t-strong" style={{ marginBottom: 10 }}>{group.label}</div>
                        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                          {group.items.map((c) => (
                            <label key={c.key} style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
                              <input
                                type="checkbox"
                                checked={granted.has(c.key)}
                                onChange={() => toggle(c.key)}
                                style={{ marginTop: 3 }}
                              />
                              <span>
                                <span className="t-strong" style={{ display: "block" }}>{c.description}</span>
                                <span className="mono t-muted" style={{ fontSize: 12 }}>{c.key}</span>
                              </span>
                            </label>
                          ))}
                        </div>
                      </div>
                    ))}
                    <div className="card-pad" style={{ borderTop: "1px solid var(--border)" }}>
                      <button className="btn primary sm" onClick={save} disabled={isSaving}>
                        {isSaving ? "Saving…" : "Save"}
                      </button>
                    </div>
                  </>
                )}
              </>
            )}
          </div>
        </>
      )}

      <NewProfileModal
        open={showNew}
        onClose={() => setShowNew(false)}
        onCreated={(created) => {
          setShowNew(false);
          loadProfiles(created.id);
        }}
      />
    </section>
  );
}

function NewProfileModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (profile: ProfileOut) => void;
}) {
  const api = useApi();
  const [code, setCode] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  function reset() {
    setCode("");
    setDisplayName("");
    setError(null);
  }

  function close() {
    reset();
    onClose();
  }

  function submit() {
    if (!code.trim() || !displayName.trim()) {
      setError("Code and display name are required.");
      return;
    }
    setIsSaving(true);
    setError(null);
    createProfile(api, { code: code.trim().toUpperCase(), display_name: displayName.trim() })
      .then((created) => {
        reset();
        onCreated(created);
      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Failed to create profile.");
      })
      .finally(() => setIsSaving(false));
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title="New profile"
      footer={
        <>
          <button className="btn sm" onClick={close} disabled={isSaving}>Cancel</button>
          <div className="spacer" />
          <button className="btn primary sm" onClick={submit} disabled={isSaving}>{isSaving ? "Saving…" : "Save"}</button>
        </>
      }
    >
      <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
        <div className="field">
          <div className="lab">Code <span className="req">*</span></div>
          <input className="inp mono" value={code} onChange={(e) => setCode(e.target.value)} autoFocus
                placeholder="SUPPORT_REP" />
        </div>
        <div className="field">
          <div className="lab">Display name <span className="req">*</span></div>
          <input className="inp" value={displayName} onChange={(e) => setDisplayName(e.target.value)}
                placeholder="Support Rep" />
        </div>
        <div className="help">Starts with zero capabilities — grant what it needs after creating it.</div>
        {error && <div className="help err">{error}</div>}
      </div>
    </Modal>
  );
}
