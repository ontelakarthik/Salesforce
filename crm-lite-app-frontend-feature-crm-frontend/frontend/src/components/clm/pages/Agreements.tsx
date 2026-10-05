"use client";

import { useEffect, useState } from "react";
import Badge, { type BadgeVariant } from "../Badge";
import DataTable, { TableLink, type DataTableColumn } from "../DataTable";
import RoleOnly from "../RoleOnly";
import Spinner from "../Spinner";
import { Icon } from "../icons";
import { ApiError, useApi } from "@/lib/api/client";
import { listAccounts, type AccountOut } from "@/lib/api/crm";
import { listAgreements, type AgreementOut } from "@/lib/api/contracts";
import NewAgreementModal from "./NewAgreementModal";

const TYPE_BADGE: Record<string, BadgeVariant> = {
  NDA: "blue",
  MSA: "blue",
  SOW: "violet",
  VENDOR_MSA: "blue",
  PURCHASE_ORDER: "gray",
};

const STATUS_BADGE: Record<string, BadgeVariant> = {
  DRAFT: "amber",
  REVIEW: "amber",
  APPROVED: "blue",
  SENT: "amber",
  SIGNED: "green",
  EXPIRED: "gray",
  SUPERSEDED: "gray",
};

function formatDate(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "2-digit" });
}

function dateSortValue(value: string | null): number {
  return value ? Date.parse(value) : -Infinity;
}

function isExpiringSoon(expiryDate: string | null): boolean {
  if (!expiryDate) return false;
  return new Date(expiryDate) <= new Date(Date.now() + 30 * 24 * 60 * 60 * 1000);
}

function agreementHref(a: AgreementOut): string | undefined {
  return `/agreements/${a.id}`;
}

export default function Agreements() {
  const api = useApi();
  const [agreements, setAgreements] = useState<AgreementOut[] | null>(null);
  const [accounts, setAccounts] = useState<Record<string, AccountOut>>({});
  const [error, setError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: fetch/reset state when inputs change
    setAgreements(null);
    setError(null);
    Promise.all([listAgreements(api), listAccounts(api, { page_size: 100 })])
      .then(([agreementList, accountPage]) => {
        if (cancelled) return;
        setAgreements(agreementList);
        setAccounts(Object.fromEntries(accountPage.items.map((c) => [c.id, c])));
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Failed to load agreements.");
      });
    return () => {
      cancelled = true;
    };
  }, [api]);

  function accountName(accountId: string): string {
    return accounts[accountId]?.legal_name?.replace(/ Pvt\. Ltd\.$/, "") ?? accountId;
  }

  const columns: DataTableColumn<AgreementOut>[] = [
    {
      key: "reference",
      label: "Reference",
      sortable: true,
      className: "mono",
      sortValue: (a) => a.id,
      render: (a) => <TableLink href={agreementHref(a)}>{a.id}</TableLink>,
    },
    {
      key: "type",
      label: "Type",
      sortable: true,
      sortValue: (a) => a.agreement_type,
      render: (a) => <Badge variant={TYPE_BADGE[a.agreement_type] ?? "gray"}>{a.agreement_type}</Badge>,
    },
    {
      key: "account",
      label: "Account",
      sortable: true,
      sortValue: (a) => accountName(a.account_id),
      render: (a) => accountName(a.account_id),
    },
    {
      key: "status",
      label: "Status",
      sortable: true,
      sortValue: (a) => a.status,
      render: (a) => <Badge variant={STATUS_BADGE[a.status] ?? "gray"}>{a.status}</Badge>,
    },
    {
      key: "effective",
      label: "Effective",
      sortable: true,
      sortValue: (a) => dateSortValue(a.effective_date),
      render: (a) => <span className={a.effective_date ? undefined : "empty-hint"}>{formatDate(a.effective_date)}</span>,
    },
    {
      key: "expiry",
      label: "Expiry",
      sortable: true,
      sortValue: (a) => dateSortValue(a.expiry_date),
      render: (a) => (
        <span
          style={isExpiringSoon(a.expiry_date) ? { color: "var(--amber)" } : undefined}
          className={a.expiry_date ? undefined : "empty-hint"}
        >
          {formatDate(a.expiry_date)}
        </span>
      ),
    },
    {
      key: "sla",
      label: "SLA",
      render: (a) =>
        a.sla_breached_at ? (
          <Badge variant="red">Breached</Badge>
        ) : a.sla_due_at ? (
          <Badge variant="green">On time</Badge>
        ) : (
          <span className="empty-hint">—</span>
        ),
    },
  ];

  // NDAs (regardless of status) plus anything breaching SLA regardless of
  // type land in the "legal review" section; everything else (MSA/SOW, plus
  // the less common VENDOR_MSA/PURCHASE_ORDER types) falls into the
  // commercial-agreements section — every row appears in exactly one table.
  const ndaAndBreached = (agreements ?? []).filter((a) => a.agreement_type === "NDA" || a.sla_breached_at);
  const commercial = (agreements ?? []).filter((a) => !(a.agreement_type === "NDA" || a.sla_breached_at));

  return (
    <section className="page active">
      <div className="pagehead">
        <div>
          <h1>Agreements</h1>
          <div className="sub">Everything pending, expiring, and breaching — in one place</div>
        </div>
        <div className="spacer" />
        <RoleOnly roles={["ACCOUNT_EXEC", "ADMIN"]}>
          <button className="btn primary" onClick={() => setShowNew(true)}>
            <Icon name="plus" />
            New agreement
          </button>
        </RoleOnly>
      </div>
      {error && <div className="help err" style={{ margin: "12px 0" }}>{error}</div>}
      {agreements === null && !error ? (
        <div className="card card-pad loading-inline"><Spinner /> Loading agreements…</div>
      ) : (
        <>
          <h2 style={{ fontSize: 15, marginBottom: 10 }}>NDAs &amp; SLA Breached</h2>
          <DataTable
            columns={columns}
            rows={ndaAndBreached}
            rowKey={(a) => a.id}
            rowHref={agreementHref}
            searchPlaceholder="Search reference, account..."
            searchValue={(a) => `${a.id} ${accountName(a.account_id)} ${a.agreement_type}`}
          />
          <h2 style={{ fontSize: 15, margin: "24px 0 10px" }}>MSAs &amp; SOWs</h2>
          <DataTable
            columns={columns}
            rows={commercial}
            rowKey={(a) => a.id}
            rowHref={agreementHref}
            searchPlaceholder="Search reference, account..."
            searchValue={(a) => `${a.id} ${accountName(a.account_id)} ${a.agreement_type}`}
          />
        </>
      )}
      <NewAgreementModal
        open={showNew}
        onClose={() => setShowNew(false)}
        accounts={Object.values(accounts)}
        onCreated={(created) => setAgreements((prev) => (prev ? [created, ...prev] : [created]))}
      />
    </section>
  );
}
