"use client";

import { useEffect, useState } from "react";
import DataTable, { type DataTableColumn } from "../DataTable";
import Spinner from "../Spinner";
import { ApiError, useApi } from "@/lib/api/client";
import { useEmployeeDirectory } from "@/lib/api/identity";
import { listAudit, type AuditLogOut } from "@/lib/api/activity";

function formatDateTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function buildColumns(employeeLabel: (id: string | null) => string): DataTableColumn<AuditLogOut>[] {
  return [
    {
      key: "entity",
      label: "Entity",
      sortable: true,
      sortValue: (r) => `${r.entity_type} ${r.entity_id}`,
      render: (r) => <span className="mono">{r.entity_type} · {r.entity_id}</span>,
    },
    {
      key: "action",
      label: "Action",
      sortable: true,
      sortValue: (r) => r.action,
      render: (r) => r.action,
    },
    {
      key: "field",
      label: "Field changed",
      render: (r) => r.field_changed ?? "—",
    },
    {
      key: "change",
      label: "Old → New",
      render: (r) =>
        r.old_value || r.new_value ? (
          <span className="t-muted">{r.old_value ?? "—"} → {r.new_value ?? "—"}</span>
        ) : (
          <span className="empty-hint">—</span>
        ),
    },
    {
      key: "by",
      label: "Performed by",
      render: (r) => employeeLabel(r.performed_by_employee_id),
    },
    {
      key: "at",
      label: "Performed at",
      sortable: true,
      className: "t-muted",
      sortValue: (r) => Date.parse(r.performed_at),
      render: (r) => formatDateTime(r.performed_at),
    },
  ];
}

export default function AuditLog() {
  const api = useApi();
  const { label } = useEmployeeDirectory();
  const columns = buildColumns(label);
  const [rows, setRows] = useState<AuditLogOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [entityType, setEntityType] = useState("");
  const [entityId, setEntityId] = useState("");

  useEffect(() => {
    let cancelled = false;
    setRows(null);
    setError(null);
    listAudit(api, {
      entity_type: entityType.trim() || undefined,
      entity_id: entityId.trim() || undefined,
    })
      .then((data) => {
        if (!cancelled) setRows(data);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Failed to load the audit log.");
      });
    return () => {
      cancelled = true;
    };
  }, [api, entityType, entityId]);

  return (
    <section className="page active">
      <div className="pagehead">
        <div>
          <h1>Audit Log</h1>
          <div className="sub">Every tracked field change, system-wide</div>
        </div>
      </div>
      <div className="fields" style={{ gridTemplateColumns: "repeat(2, 1fr)", marginBottom: 16 }}>
        <div className="field">
          <div className="lab">Entity type</div>
          <input
            className="inp"
            value={entityType}
            onChange={(e) => setEntityType(e.target.value)}
            placeholder="e.g. account, agreement, opportunity"
          />
        </div>
        <div className="field">
          <div className="lab">Entity ID</div>
          <input className="inp" value={entityId} onChange={(e) => setEntityId(e.target.value)} placeholder="e.g. ACC-00001" />
        </div>
      </div>
      {error && <div className="help err" style={{ margin: "12px 0" }}>{error}</div>}
      {rows === null && !error ? (
        <div className="card card-pad loading-inline"><Spinner /> Loading audit log…</div>
      ) : (
        <DataTable
          columns={columns}
          rows={rows ?? []}
          rowKey={(r) => r.id}
          searchPlaceholder="Search action, field..."
          searchValue={(r) => `${r.entity_type} ${r.entity_id} ${r.action} ${r.field_changed ?? ""}`}
        />
      )}
    </section>
  );
}
