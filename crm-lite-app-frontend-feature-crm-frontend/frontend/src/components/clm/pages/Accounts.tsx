"use client";

import { useEffect, useState } from "react";
import AccessDenied from "../AccessDenied";
import RoleOnly from "../RoleOnly";
import Badge, { type BadgeVariant } from "../Badge";
import DataTable, { TableLink, type DataTableColumn } from "../DataTable";
import Spinner from "../Spinner";
import { Icon } from "../icons";
import { ApiError, useApi } from "@/lib/api/client";
import { listAccounts, type AccountOut } from "@/lib/api/crm";
import NewAccountModal from "./NewAccountModal";

const ACCOUNT_TYPE_BADGE: Record<string, BadgeVariant> = {
  CLIENT: "green",
  PROSPECT: "blue",
  PARTNER: "teal",
  VENDOR: "gray",
};

function accountHref(account: AccountOut): string | undefined {
  return `/accounts/${account.id}`;
}

const TYPE_FILTERS = [
  { value: "ALL", label: "All" },
  { value: "PROSPECT", label: "Prospect" },
  { value: "CLIENT", label: "Client" },
  { value: "PARTNER", label: "Partner" },
  { value: "VENDOR", label: "Vendor" },
];

const COLUMNS: DataTableColumn<AccountOut>[] = [
  {
    key: "id",
    label: "ID",
    sortable: true,
    className: "mono t-muted",
    sortValue: (c) => c.id,
    render: (c) => c.id,
  },
  {
    key: "legal_name",
    label: "Legal name",
    sortable: true,
    sortValue: (c) => c.legal_name ?? "",
    render: (c) => <TableLink href={accountHref(c)}>{(c.legal_name ?? "—").replace(/ Pvt\. Ltd\.$/, "")}</TableLink>,
  },
  {
    key: "type",
    label: "Type",
    render: (c) => <Badge variant={ACCOUNT_TYPE_BADGE[c.account_type] ?? "gray"}>{c.account_type}</Badge>,
  },
  {
    key: "industry",
    label: "Industry",
    sortable: true,
    sortValue: (c) => c.industry ?? "",
    render: (c) => c.industry ?? "—",
  },
  {
    key: "created",
    label: "Created",
    sortable: true,
    className: "t-muted",
    sortValue: (c) => (c.created_at ? Date.parse(c.created_at) : 0),
    render: (c) =>
      c.created_at
        ? new Date(c.created_at).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" })
        : "—",
  },
];

export default function Accounts() {
  const api = useApi();
  const [accounts, setAccounts] = useState<AccountOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [typeFilter, setTypeFilter] = useState("ALL");

  useEffect(() => {
    let cancelled = false;
    setAccounts(null);
    setError(null);
    setForbidden(false);
    // page_size=100: DataTable does its own client-side search/sort/paging over
    // whatever rows it's given, so one large page covers the demo dataset.
    listAccounts(api, { page_size: 100 })
      .then((page) => {
        if (!cancelled) setAccounts(page.items);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.code === "FORBIDDEN") setForbidden(true);
        else setError(err instanceof ApiError ? err.message : "Failed to load accounts.");
      });
    return () => {
      cancelled = true;
    };
  }, [api]);

  if (forbidden) return <AccessDenied what="Accounts" />;

  return (
    <section className="page active">
      <div className="pagehead">
        <div>
          <h1>Accounts</h1>
          <div className="sub">All counterparties you can access</div>
        </div>
        <div className="spacer" />
        <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
          <button className="btn primary" onClick={() => setShowNew(true)}>
            <Icon name="plus" />
            New account
          </button>
        </RoleOnly>
      </div>
      <div className="filterbar">
        {TYPE_FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            className={`chip${typeFilter === f.value ? " on" : ""}`}
            onClick={() => setTypeFilter(f.value)}
          >
            {f.label}
          </button>
        ))}
      </div>
      {error && <div className="help err" style={{ margin: "12px 0" }}>{error}</div>}
      {accounts === null && !error ? (
        <div className="card card-pad loading-inline"><Spinner /> Loading accounts…</div>
      ) : (
        <DataTable
          columns={COLUMNS}
          rows={typeFilter === "ALL" ? (accounts ?? []) : (accounts ?? []).filter((c) => c.account_type === typeFilter)}
          rowKey={(c) => c.id}
          rowHref={accountHref}
          searchPlaceholder="Search account name, ID..."
          searchValue={(c) => `${c.id} ${c.legal_name} ${c.industry ?? ""}`}
        />
      )}
      <NewAccountModal
        open={showNew}
        onClose={() => setShowNew(false)}
        onCreated={(created) => {
          setAccounts((prev) => (prev ? [created, ...prev] : [created]));
        }}
      />
    </section>
  );
}
