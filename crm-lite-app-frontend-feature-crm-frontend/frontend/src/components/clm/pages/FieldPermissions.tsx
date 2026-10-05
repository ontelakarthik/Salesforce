"use client";

import { useEffect, useState } from "react";
import Spinner from "../Spinner";
import { Icon } from "../icons";
import { ApiError, useApi } from "@/lib/api/client";
import { listProfiles, type ProfileOut } from "@/lib/api/profiles";
import {
  FLS_FIELDS,
  listFieldPermissions,
  saveFieldPermissions,
  type FieldPermissionEntry,
  type FlsObjectName,
} from "@/lib/api/fieldPermissions";

const OBJECTS: { value: FlsObjectName; label: string; icon: "userCircle" | "building" | "trendingUp" }[] = [
  { value: "LEAD", label: "Lead", icon: "userCircle" },
  { value: "ACCOUNT", label: "Account", icon: "building" },
  { value: "OPPORTUNITY", label: "Opportunity", icon: "trendingUp" },
];

type Cell = { visible: boolean; editable: boolean };
const DEFAULT_CELL: Cell = { visible: true, editable: true };

function gridFor(rows: FieldPermissionEntry[], profileId: number, object: FlsObjectName): Record<string, Cell> {
  const next: Record<string, Cell> = {};
  for (const { field } of FLS_FIELDS[object]) next[field] = { ...DEFAULT_CELL };
  for (const row of rows) {
    if (row.role_id === profileId) next[row.field_name] = { visible: row.visible, editable: row.editable };
  }
  return next;
}

/** Salesforce's real Field-Level Security flow: pick a profile, pick an
 * object, configure that one profile+object's fields. Replaces the old
 * single "every profile × every field" matrix. The backend's PUT still
 * replaces an object's ENTIRE row set (every profile at once, see
 * crm_service.save_field_permissions) — so saving one profile's view here
 * fetches the full current set for that object first, merges in just this
 * profile's edits, and PUTs the merged whole, preserving every other
 * profile's configured restrictions on the same object. */
export default function FieldPermissions() {
  const api = useApi();
  const [profiles, setProfiles] = useState<ProfileOut[] | null>(null);
  const [selectedProfile, setSelectedProfile] = useState<ProfileOut | null>(null);
  const [selectedObject, setSelectedObject] = useState<FlsObjectName | null>(null);
  const [allEntries, setAllEntries] = useState<FieldPermissionEntry[] | null>(null);
  const [grid, setGrid] = useState<Record<string, Cell> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    listProfiles(api)
      .then((rows) => setProfiles(rows.filter((p) => p.code !== "ADMIN")))
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Failed to load profiles.");
      });
  }, [api]);

  useEffect(() => {
    if (!selectedObject || !selectedProfile) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: fetch/reset state when inputs change
      setAllEntries(null);
      setGrid(null);
      return;
    }
    let cancelled = false;
    setAllEntries(null);
    setGrid(null);
    setError(null);
    setSaved(false);
    listFieldPermissions(api, selectedObject)
      .then((rows) => {
        if (cancelled) return;
        setAllEntries(rows);
        setGrid(gridFor(rows, selectedProfile.id, selectedObject));
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Failed to load field permissions.");
      });
    return () => {
      cancelled = true;
    };
  }, [api, selectedObject, selectedProfile]);

  function setCell(field: string, patch: Partial<Cell>) {
    setGrid((prev) => {
      if (!prev) return prev;
      const current = { ...prev[field], ...patch };
      if (!current.visible) current.editable = false; // can't edit what you can't see
      return { ...prev, [field]: current };
    });
    setSaved(false);
  }

  function save() {
    if (!selectedProfile || !selectedObject || !allEntries || !grid) return;
    setIsSaving(true);
    setError(null);
    const otherProfiles = allEntries.filter((e) => e.role_id !== selectedProfile.id);
    const thisProfile: FieldPermissionEntry[] = Object.entries(grid)
      .filter(([, cell]) => !cell.visible || !cell.editable) // only deviations from the default need a row
      .map(([field_name, cell]) => ({
        role_id: selectedProfile.id, object_name: selectedObject, field_name,
        visible: cell.visible, editable: cell.editable,
      }));
    saveFieldPermissions(api, selectedObject, [...otherProfiles, ...thisProfile])
      .then((rows) => {
        setAllEntries(rows);
        setSaved(true);
      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Failed to save field permissions.");
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
          <h1 title="Restricts which individual fields a profile can see or edit on a record it can already otherwise access — different from Object Permissions, which controls whether the profile can access the record at all.">
            Field Permissions
          </h1>
          <div className="sub">Pick a profile, then an object, to configure who can see and edit each field.</div>
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
          {grid === null ? (
            <div className="card-pad loading-inline"><Spinner /> Loading fields…</div>
          ) : (
            <>
              <div style={{ overflowX: "auto" }}>
                <table>
                  <thead>
                    <tr>
                      <th>Field</th>
                      <th style={{ textAlign: "center" }} title="Whether this profile can see the field's value at all. Unchecking it also nulls the value out of every API response, not just the UI.">Visible</th>
                      <th style={{ textAlign: "center" }} title="Whether this profile can change the field's value. Can't be checked unless Visible is checked too.">Editable</th>
                    </tr>
                  </thead>
                  <tbody>
                    {FLS_FIELDS[selectedObject].map(({ field, label }) => {
                      const cell = grid[field] ?? DEFAULT_CELL;
                      return (
                        <tr key={field}>
                          <td className="t-strong">{label}</td>
                          <td style={{ textAlign: "center" }}>
                            <input type="checkbox" checked={cell.visible}
                                  onChange={(e) => setCell(field, { visible: e.target.checked })} />
                          </td>
                          <td style={{ textAlign: "center" }}>
                            <input type="checkbox" checked={cell.editable} disabled={!cell.visible}
                                  onChange={(e) => setCell(field, { editable: e.target.checked })} />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
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
