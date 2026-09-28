"use client";

import { useEffect, useMemo, useState } from "react";
import Badge, { type BadgeVariant } from "../Badge";
import DataTable, { TableLink, type DataTableColumn } from "../DataTable";
import Spinner from "../Spinner";
import { ApiError, useApi } from "@/lib/api/client";
import { listAccounts, listOpportunities, type AccountOut, type OpportunityOut } from "@/lib/api/crm";

const STAGE_BADGE: Record<string, BadgeVariant> = {
  NEW: "gray",
  QUALIFIED: "blue",
  PROPOSAL: "amber",
  NEGOTIATION: "blue",
  WON: "green",
  LOST: "gray",
};

const FILTERS = [
  { value: "ALL", label: "All" },
  { value: "WITH", label: "With opportunities" },
  { value: "WITHOUT", label: "Without opportunities" },
];

interface AccountRow extends AccountOut {
  opportunities: OpportunityOut[];
}

function accountHref(row: AccountRow): string | undefined {
  return `/accounts/${row.id}`;
}

export default function Reports() {
  const api = useApi();
  const [accounts, setAccounts] = useState<AccountOut[] | null>(null);
  const [opportunities, setOpportunities] = useState<OpportunityOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("ALL");

  useEffect(() => {
    let cancelled = false;
    setAccounts(null);
    setError(null);
    Promise.all([listAccounts(api, { page_size: 100 }), listOpportunities(api)])
      .then(([accountPage, opportunityList]) => {
        if (cancelled) return;
        setAccounts(accountPage.items);
        setOpportunities(opportunityList);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Failed to load report data.");
      });
    return () => {
      cancelled = true;
    };
  }, [api]);

  const rows: AccountRow[] = useMemo(() => {
    const byAccount = new Map<string, OpportunityOut[]>();
    for (const o of opportunities) {
      const list = byAccount.get(o.account_id);
      if (list) list.push(o);
      else byAccount.set(o.account_id, [o]);
    }
    return (accounts ?? []).map((c) => ({ ...c, opportunities: byAccount.get(c.id) ?? [] }));
  }, [accounts, opportunities]);

  const filteredRows = rows.filter((r) => {
    if (filter === "WITH") return r.opportunities.length > 0;
    if (filter === "WITHOUT") return r.opportunities.length === 0;
    return true;
  });

  const columns: DataTableColumn<AccountRow>[] = [
    {
      key: "id",
      label: "ID",
      sortable: true,
      className: "mono t-muted",
      sortValue: (r) => r.id,
      render: (r) => r.id,
    },
    {
      key: "legal_name",
      label: "Legal name",
      sortable: true,
      sortValue: (r) => r.legal_name ?? "",
      render: (r) => <TableLink href={accountHref(r)}>{(r.legal_name ?? "—").replace(/ Pvt\. Ltd\.$/, "")}</TableLink>,
    },
    {
      key: "type",
      label: "Type",
      render: (r) => <Badge variant="gray">{r.account_type}</Badge>,
    },
    {
      key: "count",
      label: "Opportunities",
      sortable: true,
      className: "num",
      sortValue: (r) => r.opportunities.length,
      render: (r) => r.opportunities.length,
    },
    {
      key: "opps",
      label: "Linked opportunities",
      render: (r) =>
        r.opportunities.length > 0 ? (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {r.opportunities.map((o) => (
              <Badge key={o.id} variant={STAGE_BADGE[o.stage] ?? "gray"}>{o.name} · {o.stage}</Badge>
            ))}
          </div>
        ) : (
          <span className="empty-hint">None</span>
        ),
    },
  ];

  return (
    <section className="page active">
      <div className="pagehead">
        <div>
          <h1>Reports</h1>
          <div className="sub">Accounts with and without linked opportunities</div>
        </div>
      </div>
      <div className="filterbar">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            className={`chip${filter === f.value ? " on" : ""}`}
            onClick={() => setFilter(f.value)}
          >
            {f.label}
          </button>
        ))}
      </div>
      {error && <div className="help err" style={{ margin: "12px 0" }}>{error}</div>}
      {accounts === null && !error ? (
        <div className="card card-pad loading-inline"><Spinner /> Loading report…</div>
      ) : (
        <DataTable
          columns={columns}
          rows={filteredRows}
          rowKey={(r) => r.id}
          rowHref={accountHref}
          searchPlaceholder="Search account name, ID..."
          searchValue={(r) => `${r.id} ${r.legal_name} ${r.opportunities.map((o) => o.name).join(" ")}`}
        />
      )}
    </section>
  );
}
