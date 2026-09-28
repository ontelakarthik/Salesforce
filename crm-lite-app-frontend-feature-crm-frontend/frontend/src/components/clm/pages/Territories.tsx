"use client";

import { useEffect, useState, useTransition } from "react";
import Badge from "../Badge";
import Modal from "../Modal";
import RoleOnly from "../RoleOnly";
import Spinner from "../Spinner";
import { CountrySelect } from "../CountryStateFields";
import { ApiError, useApi } from "@/lib/api/client";
import { getRegionOptions } from "@/lib/geo";
import {
  addLookup,
  listLookups,
  updateLookup,
  type LookupOut,
} from "@/lib/api/admin";

const TABLE = "territory";

/** Territory management — a Salesforce Territory2-inspired hierarchy
 * (Name/Code/Description/Parent Territory/Country/Region/Status), built on
 * the same generic /admin/lookups/territory endpoint every other lookup
 * table uses (see admin_service._LOOKUP_TABLES) — no bespoke API. Kept as
 * its own dedicated page (not a Lookups.tsx tab) because Territory's
 * hierarchy (a Parent Territory picker resolved by id, not code) doesn't
 * fit the generic flat-lookup table/modal shape the other lookup tables
 * share. */
export default function Territories() {
  const api = useApi();
  const [rows, setRows] = useState<LookupOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [editing, setEditing] = useState<LookupOut | null>(null);

  function load() {
    setError(null);
    listLookups(api, TABLE)
      .then((data) => setRows(data))
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Failed to load territories.");
      });
  }

  useEffect(() => {
    setRows(null);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);

  const byId = new Map((rows ?? []).map((r) => [r.id, r]));

  function toggleActive(row: LookupOut) {
    updateLookup(api, TABLE, row.id, { is_active: !(row.is_active ?? true) })
      .then((updated) => setRows((prev) => (prev ?? []).map((x) => (x.id === updated.id ? updated : x))))
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Failed to update territory.");
      });
  }

  return (
    <section className="page active">
      <div className="pagehead">
        <div>
          <h1>Territories</h1>
          <div className="sub">
            Sales Territory hierarchy for record visibility/assignment (Employees &amp; Teams, Accounts, Leads) —
            independent of Billing Country/State.
          </div>
        </div>
        <RoleOnly roles={["ADMIN"]}>
          <button className="btn primary" onClick={() => setShowNew(true)}>+ Add Territory</button>
        </RoleOnly>
      </div>
      <div className="card">
        {error && <div className="help err" style={{ margin: "12px 16px" }}>{error}</div>}
        {rows === null && !error ? (
          <div className="card-pad loading-inline"><Spinner /> Loading territories…</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Code</th>
                <th>Description</th>
                <th>Parent Territory</th>
                <th>Country</th>
                <th>Region</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {(rows ?? []).map((row) => (
                <tr key={row.id}>
                  <td>{row.display_name}</td>
                  <td className="mono">{row.code ?? <span className="empty-hint">—</span>}</td>
                  <td>{row.description ?? <span className="empty-hint">—</span>}</td>
                  <td>
                    {row.parent_territory_id != null
                      ? byId.get(row.parent_territory_id)?.display_name ?? <span className="empty-hint">—</span>
                      : <span className="empty-hint">—</span>}
                  </td>
                  <td>{row.country ?? <span className="empty-hint">—</span>}</td>
                  <td>{row.region ?? <span className="empty-hint">—</span>}</td>
                  <td>
                    {row.is_active === false
                      ? <Badge variant="gray">Inactive</Badge>
                      : <Badge variant="green">Active</Badge>}
                  </td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    <RoleOnly roles={["ADMIN"]}>
                      <button className="btn sm" onClick={() => setEditing(row)}>Edit</button>{" "}
                      <button className="btn sm" onClick={() => toggleActive(row)}>
                        {row.is_active === false ? "Activate" : "Deactivate"}
                      </button>
                    </RoleOnly>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <TerritoryFormModal
        mode="create"
        open={showNew}
        row={null}
        territories={rows ?? []}
        onClose={() => setShowNew(false)}
        onSaved={(created) => {
          setRows((prev) => (prev ? [...prev, created] : [created]));
          setShowNew(false);
        }}
      />
      <TerritoryFormModal
        mode="edit"
        open={editing !== null}
        row={editing}
        territories={rows ?? []}
        onClose={() => setEditing(null)}
        onSaved={(updated) => {
          setRows((prev) => (prev ?? []).map((x) => (x.id === updated.id ? updated : x)));
          setEditing(null);
        }}
      />
    </section>
  );
}

function TerritoryFormModal({
  mode,
  open,
  row,
  territories,
  onClose,
  onSaved,
}: {
  mode: "create" | "edit";
  open: boolean;
  row: LookupOut | null;
  /** Every existing territory — for the Parent Territory picker (by id/Name,
   * never Code) and, on edit, excluding this row itself from that list. */
  territories: LookupOut[];
  onClose: () => void;
  onSaved: (row: LookupOut) => void;
}) {
  const api = useApi();
  const [code, setCode] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [country, setCountry] = useState("");
  const [region, setRegion] = useState("");
  const [parentTerritoryId, setParentTerritoryId] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    if (!open) return;
    setCode(row?.code ?? "");
    setDisplayName(row?.display_name ?? "");
    setDescription(row?.description ?? "");
    setCountry(row?.country ?? "");
    setRegion(row?.region ?? "");
    setParentTerritoryId(row?.parent_territory_id != null ? String(row.parent_territory_id) : "");
    setIsActive(row?.is_active ?? true);
    setError(null);
  }, [open, row]);

  function submit() {
    if (!displayName.trim()) {
      setError("Name is required.");
      return;
    }
    if (!country) {
      setError("Country is required.");
      return;
    }
    const payload = {
      code: code.trim() ? code.trim().toUpperCase() : undefined,
      display_name: displayName.trim(),
      description: description.trim() || null,
      country,
      region: region || null,
      parent_territory_id: parentTerritoryId ? Number(parentTerritoryId) : null,
      is_active: isActive,
    };
    startTransition(async () => {
      try {
        const saved = mode === "create"
          ? await addLookup(api, TABLE, payload)
          : await updateLookup(api, TABLE, row!.id, payload);
        onSaved(saved);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to save territory.");
      }
    });
  }

  const parentOptions = territories.filter((t) => t.id !== row?.id);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={mode === "create" ? "Add Territory" : `Edit ${row?.display_name ?? "territory"}`}
      footer={
        <>
          <button className="btn sm" onClick={onClose} disabled={isPending}>Cancel</button>
          <div className="spacer" />
          <button className="btn primary sm" onClick={submit} disabled={isPending}>{isPending ? "Saving…" : "Save"}</button>
        </>
      }
    >
      <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
        <div className="field">
          <div className="lab">Name <span className="req">*</span></div>
          <input className="inp" value={displayName} onChange={(e) => setDisplayName(e.target.value)}
                placeholder="e.g. USA - East" autoFocus />
        </div>
        <div className="field">
          <div className="lab">Code</div>
          <input className="inp mono" value={code} onChange={(e) => setCode(e.target.value)} placeholder="e.g. USA-E" />
          <div className="help">Optional — never used as the relationship key (Territory is referenced by id).</div>
        </div>
        <div className="field">
          <div className="lab">Description</div>
          <textarea className="inp" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
        <div className="field">
          <div className="lab">Parent Territory</div>
          <select className="inp" value={parentTerritoryId} onChange={(e) => setParentTerritoryId(e.target.value)}>
            <option value="">— none —</option>
            {parentOptions.map((t) => (
              <option key={t.id} value={t.id}>{t.display_name}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <div className="lab">Country <span className="req">*</span></div>
          <CountrySelect
            value={country}
            onChange={(c) => {
              setCountry(c);
              setRegion("");
            }}
          />
        </div>
        <div className="field">
          <div className="lab">Region</div>
          <select className="inp" disabled={!country} value={region} onChange={(e) => setRegion(e.target.value)}>
            <option value="">{country ? "— none —" : "—"}</option>
            {getRegionOptions(country).map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
          <div className="help">
            Optional — a country-wide/top-level territory (e.g. &quot;USA&quot; itself) has no single region.
          </div>
        </div>
        <div className="field">
          <div className="lab">Status <span className="req">*</span></div>
          <label className="val" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
            Active
          </label>
        </div>
        {error && <div className="help err">{error}</div>}
      </div>
    </Modal>
  );
}
