"use client";

import { useEffect, useState, useTransition } from "react";
import Badge from "../Badge";
import Modal from "../Modal";
import RoleOnly from "../RoleOnly";
import Spinner from "../Spinner";
import { ApiError, useApi } from "@/lib/api/client";
import {
  addLookup,
  listLookups,
  updateLookup,
  type LookupOut,
  type LookupTable,
} from "@/lib/api/admin";

type ExtraColumn = { header: string; render: (row: LookupOut) => React.ReactNode };

const SLA_COLUMN: ExtraColumn = {
  header: "Default SLA (hrs)",
  render: (row) => <span className="num">{row.default_sla_hours ?? 0}</span>,
};

const TERMINAL_COLUMN: ExtraColumn = {
  header: "Terminal",
  render: (row) => (row.is_terminal ? <Badge variant="gray">Terminal</Badge> : <span className="empty-hint">—</span>),
};

const LOOKUP_CONFIGS: { label: string; table: LookupTable; extraColumns: ExtraColumn[]; helpText: string }[] = [
  {
    label: "Agreement types",
    table: "agreement_type",
    extraColumns: [SLA_COLUMN],
    helpText: "Code is uppercase, unique and immutable once created. Values in use can't be deleted — deactivate instead.",
  },
  {
    label: "Agreement statuses",
    table: "agreement_status",
    extraColumns: [TERMINAL_COLUMN],
    helpText: "Terminal statuses close out an agreement's lifecycle and can't transition further.",
  },
  {
    label: "Account types",
    table: "account_type",
    extraColumns: [],
    helpText: "Code is uppercase, unique and immutable once created. Values in use can't be deleted — deactivate instead.",
  },
  {
    label: "Project statuses",
    table: "project_status",
    extraColumns: [TERMINAL_COLUMN],
    helpText: "Terminal statuses close out a project's lifecycle and can't transition further.",
  },
  {
    label: "Opportunity stages",
    table: "opportunity_stage",
    extraColumns: [TERMINAL_COLUMN],
    helpText: "Terminal stages (Won, Lost) close out a deal and can't transition further.",
  },
  {
    label: "Contact types",
    table: "contact_type",
    extraColumns: [],
    helpText: "Code is uppercase, unique and immutable once created. Values in use can't be deleted — deactivate instead.",
  },
];

export default function Lookups() {
  const api = useApi();
  const [active, setActive] = useState(LOOKUP_CONFIGS[0].label);
  const config = LOOKUP_CONFIGS.find((c) => c.label === active) ?? LOOKUP_CONFIGS[0];
  const [rows, setRows] = useState<LookupOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [editing, setEditing] = useState<LookupOut | null>(null);

  useEffect(() => {
    let cancelled = false;
    setRows(null);
    setError(null);
    listLookups(api, config.table)
      .then((data) => {
        if (!cancelled) setRows(data);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Failed to load values.");
      });
    return () => {
      cancelled = true;
    };
  }, [api, config.table]);

  const hasSlaColumn = config.extraColumns.includes(SLA_COLUMN);
  const hasTerminalColumn = config.extraColumns.includes(TERMINAL_COLUMN);

  return (
    <section className="page active">
      <div className="pagehead">
        <div>
          <h1>Lookups</h1>
          <div className="sub">Manage fixed value sets without a code deploy</div>
        </div>
      </div>
      <div className="adminrail">
        <div className="lookup-rail">
          {LOOKUP_CONFIGS.map((c) => (
            <button key={c.label} className={active === c.label ? "on" : ""} onClick={() => setActive(c.label)}>
              {c.label}
            </button>
          ))}
        </div>
        <div className="card">
          <div className="card-head">
            <h3>{config.label}</h3>
            <div className="spacer" />
            <RoleOnly roles={["ADMIN"]}>
              <button className="btn sm" onClick={() => setShowNew(true)}>Add value</button>
            </RoleOnly>
          </div>
          {error && <div className="help err" style={{ margin: "12px 16px" }}>{error}</div>}
          {rows === null && !error ? (
            <div className="card-pad loading-inline"><Spinner /> Loading…</div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Code</th>
                  <th>Display name</th>
                  {config.extraColumns.map((col) => (
                    <th key={col.header}>{col.header}</th>
                  ))}
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {(rows ?? []).map((row) => (
                  <tr key={row.id}>
                    <td className="mono">{row.code}</td>
                    <td>{row.display_name}</td>
                    {config.extraColumns.map((col) => (
                      <td key={col.header}>{col.render(row)}</td>
                    ))}
                    <td style={{ textAlign: "right" }}>
                      <RoleOnly roles={["ADMIN"]}>
                        <button className="btn sm" onClick={() => setEditing(row)}>Edit</button>
                      </RoleOnly>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="card-pad" style={{ borderTop: "1px solid var(--border)" }}>
            <div className="help">{config.helpText}</div>
          </div>
        </div>
      </div>
      <NewLookupModal
        open={showNew}
        table={config.table}
        label={config.label}
        hasSlaColumn={hasSlaColumn}
        hasTerminalColumn={hasTerminalColumn}
        onClose={() => setShowNew(false)}
        onCreated={(created) => setRows((prev) => (prev ? [...prev, created] : [created]))}
      />
      <EditLookupModal
        row={editing}
        table={config.table}
        hasSlaColumn={hasSlaColumn}
        hasTerminalColumn={hasTerminalColumn}
        onClose={() => setEditing(null)}
        onSaved={(updated) => setRows((prev) => (prev ?? []).map((x) => (x.id === updated.id ? updated : x)))}
      />
    </section>
  );
}

function NewLookupModal({
  open,
  table,
  label,
  hasSlaColumn,
  hasTerminalColumn,
  onClose,
  onCreated,
}: {
  open: boolean;
  table: LookupTable;
  label: string;
  hasSlaColumn: boolean;
  hasTerminalColumn: boolean;
  onClose: () => void;
  onCreated: (row: LookupOut) => void;
}) {
  const api = useApi();
  const [code, setCode] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [slaHours, setSlaHours] = useState("");
  const [isTerminal, setIsTerminal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  function reset() {
    setCode("");
    setDisplayName("");
    setSlaHours("");
    setIsTerminal(false);
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
    startTransition(async () => {
      try {
        const created = await addLookup(api, table, {
          code: code.trim().toUpperCase(),
          display_name: displayName.trim(),
          is_terminal: hasTerminalColumn ? isTerminal : undefined,
          default_sla_hours: hasSlaColumn && slaHours.trim() ? Number(slaHours) : undefined,
        });
        onCreated(created);
        close();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to add value.");
      }
    });
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title={`Add ${label.toLowerCase().replace(/s$/, "")}`}
      footer={
        <>
          <button className="btn sm" onClick={close} disabled={isPending}>Cancel</button>
          <div className="spacer" />
          <button className="btn primary sm" onClick={submit} disabled={isPending}>{isPending ? "Saving…" : "Save"}</button>
        </>
      }
    >
      <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
        <div className="field">
          <div className="lab">Code <span className="req">*</span></div>
          <input className="inp mono" value={code} onChange={(e) => setCode(e.target.value)} placeholder="e.g. RENEWAL" autoFocus />
          <div className="help">Uppercase, immutable once created.</div>
        </div>
        <div className="field">
          <div className="lab">Display name <span className="req">*</span></div>
          <input className="inp" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        </div>
        {hasSlaColumn && (
          <div className="field">
            <div className="lab">Default SLA (hrs)</div>
            <input className="inp" type="number" value={slaHours} onChange={(e) => setSlaHours(e.target.value)} />
          </div>
        )}
        {hasTerminalColumn && (
          <div className="field">
            <label className="val" style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <input type="checkbox" checked={isTerminal} onChange={(e) => setIsTerminal(e.target.checked)} />
              Terminal
            </label>
          </div>
        )}
        {error && <div className="help err">{error}</div>}
      </div>
    </Modal>
  );
}

function EditLookupModal({
  row,
  table,
  hasSlaColumn,
  hasTerminalColumn,
  onClose,
  onSaved,
}: {
  row: LookupOut | null;
  table: LookupTable;
  hasSlaColumn: boolean;
  hasTerminalColumn: boolean;
  onClose: () => void;
  onSaved: (row: LookupOut) => void;
}) {
  const api = useApi();
  const [displayName, setDisplayName] = useState("");
  const [slaHours, setSlaHours] = useState("");
  const [isTerminal, setIsTerminal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    if (!row) return;
    setDisplayName(row.display_name);
    setSlaHours(row.default_sla_hours != null ? String(row.default_sla_hours) : "");
    setIsTerminal(row.is_terminal ?? false);
    setError(null);
  }, [row]);

  function submit() {
    if (!row) return;
    if (!displayName.trim()) {
      setError("Display name is required.");
      return;
    }
    startTransition(async () => {
      try {
        const updated = await updateLookup(api, table, row.id, {
          display_name: displayName.trim(),
          is_terminal: hasTerminalColumn ? isTerminal : undefined,
          default_sla_hours: hasSlaColumn && slaHours.trim() ? Number(slaHours) : undefined,
        });
        onSaved(updated);
        onClose();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to save value.");
      }
    });
  }

  return (
    <Modal
      open={row !== null}
      onClose={onClose}
      title={row ? `Edit ${row.display_name}` : "Edit value"}
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
          <div className="lab">Display name <span className="req">*</span></div>
          <input className="inp" value={displayName} onChange={(e) => setDisplayName(e.target.value)} autoFocus />
        </div>
        <div className="field">
          <div className="lab">Code</div>
          <div className="val mono t-muted">{row?.code}</div>
        </div>
        {hasSlaColumn && (
          <div className="field">
            <div className="lab">Default SLA (hrs)</div>
            <input className="inp" type="number" value={slaHours} onChange={(e) => setSlaHours(e.target.value)} />
          </div>
        )}
        {hasTerminalColumn && (
          <div className="field">
            <label className="val" style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <input type="checkbox" checked={isTerminal} onChange={(e) => setIsTerminal(e.target.checked)} />
              Terminal
            </label>
          </div>
        )}
        {error && <div className="help err">{error}</div>}
      </div>
    </Modal>
  );
}
