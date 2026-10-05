"use client";

import { useEffect, useState } from "react";
import AccessDenied from "../AccessDenied";
import RoleOnly from "../RoleOnly";
import Badge, { type BadgeVariant } from "../Badge";
import DataTable, { TableLink, type DataTableColumn } from "../DataTable";
import Spinner from "../Spinner";
import { Icon } from "../icons";
import { ApiError, useApi } from "@/lib/api/client";
import { listAccounts, listOpportunities, type AccountOut, type OpportunityOut } from "@/lib/api/crm";
import NewOpportunityModal from "./NewOpportunityModal";

const STAGE_BADGE: Record<string, BadgeVariant> = {
  NEW: "gray",
  QUALIFIED: "blue",
  PROPOSAL: "amber",
  NEGOTIATION: "blue",
  WON: "green",
  LOST: "gray",
};

function opportunityHref(opp: OpportunityOut): string | undefined {
  return `/opportunities/${opp.id}`;
}

const STAGE_FILTERS = [
  { value: "OPEN", label: "Open" },
  { value: "QUALIFIED", label: "Qualified" },
  { value: "PROPOSAL", label: "Proposal" },
  { value: "NEGOTIATION", label: "Negotiation" },
  { value: "WON", label: "Won" },
  { value: "LOST", label: "Lost" },
];

export default function Opportunities() {
  const api = useApi();
  const [opportunities, setOpportunities] = useState<OpportunityOut[] | null>(null);
  const [accounts, setAccounts] = useState<Record<string, AccountOut>>({});
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [stageFilter, setStageFilter] = useState("OPEN");

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: fetch/reset state when inputs change
    setOpportunities(null);
    setError(null);
    setForbidden(false);
    Promise.all([listOpportunities(api), listAccounts(api, { page_size: 100 })])
      .then(([opps, accountPage]) => {
        if (cancelled) return;
        setOpportunities(opps);
        setAccounts(Object.fromEntries(accountPage.items.map((c) => [c.id, c])));
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.code === "FORBIDDEN") setForbidden(true);
        else setError(err instanceof ApiError ? err.message : "Failed to load opportunities.");
      });
    return () => {
      cancelled = true;
    };
  }, [api]);

  if (forbidden) return <AccessDenied what="Opportunities" />;

  function accountName(accountId: string): string {
    return accounts[accountId]?.legal_name?.replace(/ Pvt\. Ltd\.$/, "") ?? accountId;
  }

  const columns: DataTableColumn<OpportunityOut>[] = [
    {
      key: "id",
      label: "ID",
      sortable: true,
      className: "mono t-muted",
      sortValue: (o) => o.id,
      render: (o) => o.id,
    },
    {
      key: "name",
      label: "Name",
      sortable: true,
      sortValue: (o) => o.name ?? "",
      render: (o) => <TableLink href={opportunityHref(o)}>{o.name ?? "—"}</TableLink>,
    },
    {
      key: "account",
      label: "Account",
      sortable: true,
      sortValue: (o) => accountName(o.account_id),
      render: (o) => accountName(o.account_id),
    },
    {
      key: "stage",
      label: "Stage",
      sortable: true,
      sortValue: (o) => o.stage,
      render: (o) => <Badge variant={STAGE_BADGE[o.stage] ?? "gray"}>{o.stage}</Badge>,
    },
    {
      key: "value",
      label: "Value",
      sortable: true,
      className: "num",
      sortValue: (o) => o.estimated_value ?? 0,
      render: (o) => (o.estimated_value != null ? `${o.currency ?? "USD"} ${o.estimated_value.toLocaleString("en-US")}` : "—"),
    },
    {
      key: "close",
      label: "Expected close",
      sortable: true,
      sortValue: (o) => (o.expected_close_date ? Date.parse(o.expected_close_date) : 0),
      render: (o) => {
        if (o.stage === "WON" || o.stage === "LOST") return <span className="t-muted">closed</span>;
        if (!o.expected_close_date) return "—";
        return new Date(o.expected_close_date).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
      },
    },
  ];

  return (
    <section className="page active">
      <div className="pagehead">
        <div>
          <h1>Opportunities</h1>
          <div className="sub">Your active pipeline</div>
        </div>
        <div className="spacer" />
        <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
          <button className="btn primary" onClick={() => setShowNew(true)}>
            <Icon name="plus" />
            New opportunity
          </button>
        </RoleOnly>
      </div>
      <div className="filterbar">
        {STAGE_FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            className={`chip${stageFilter === f.value ? " on" : ""}`}
            onClick={() => setStageFilter(f.value)}
          >
            {f.label}
          </button>
        ))}
      </div>
      {error && <div className="help err" style={{ margin: "12px 0" }}>{error}</div>}
      {opportunities === null && !error ? (
        <div className="card card-pad loading-inline"><Spinner /> Loading opportunities…</div>
      ) : (
        <DataTable
          columns={columns}
          rows={(opportunities ?? []).filter((o) =>
            stageFilter === "OPEN" ? o.stage !== "WON" && o.stage !== "LOST" : o.stage === stageFilter
          )}
          rowKey={(o) => o.id}
          rowHref={opportunityHref}
          searchPlaceholder="Search opportunity name, account..."
          searchValue={(o) => `${o.id} ${o.name} ${accountName(o.account_id)}`}
        />
      )}
      <NewOpportunityModal
        open={showNew}
        onClose={() => setShowNew(false)}
        onCreated={(created) => {
          setOpportunities((prev) => (prev ? [created, ...prev] : [created]));
        }}
      />
    </section>
  );
}
