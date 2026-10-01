"use client";

import { useEffect, useState } from "react";
import Badge, { type BadgeVariant } from "../Badge";
import DataTable, { TableLink, type DataTableColumn } from "../DataTable";
import Spinner from "../Spinner";
import { ApiError, useApi } from "@/lib/api/client";
import { listAccounts, type AccountOut } from "@/lib/api/crm";
import { listProjects, type ProjectOut } from "@/lib/api/project";

const STATUS_BADGE: Record<string, BadgeVariant> = {
  PLANNING: "blue",
  ACTIVE: "green",
  CLOSED: "gray",
};

function projectHref(project: ProjectOut): string | undefined {
  return `/projects/${project.id}`;
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export default function Projects() {
  const api = useApi();
  const [projects, setProjects] = useState<ProjectOut[] | null>(null);
  const [accounts, setAccounts] = useState<Record<string, AccountOut>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setProjects(null);
    setError(null);
    Promise.all([listProjects(api), listAccounts(api, { page_size: 100 })])
      .then(([projectList, accountPage]) => {
        if (cancelled) return;
        setProjects(projectList);
        setAccounts(Object.fromEntries(accountPage.items.map((c) => [c.id, c])));
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Failed to load projects.");
      });
    return () => {
      cancelled = true;
    };
  }, [api]);

  function accountName(accountId: string): string {
    return accounts[accountId]?.legal_name?.replace(/ Pvt\. Ltd\.$/, "") ?? accountId;
  }

  const columns: DataTableColumn<ProjectOut>[] = [
    {
      key: "id",
      label: "Reference",
      sortable: true,
      className: "mono t-muted",
      sortValue: (p) => p.id,
      render: (p) => p.id,
    },
    {
      key: "name",
      label: "Name",
      sortable: true,
      sortValue: (p) => p.name,
      render: (p) => <TableLink href={projectHref(p)}>{p.name}</TableLink>,
    },
    {
      key: "account",
      label: "Account",
      sortable: true,
      sortValue: (p) => accountName(p.account_id),
      render: (p) => accountName(p.account_id),
    },
    {
      key: "status",
      label: "Status",
      sortable: true,
      sortValue: (p) => p.status,
      render: (p) => <Badge variant={STATUS_BADGE[p.status] ?? "gray"}>{p.status}</Badge>,
    },
    {
      key: "start",
      label: "Start date",
      sortable: true,
      className: "t-muted",
      sortValue: (p) => Date.parse(p.start_date),
      render: (p) => formatDate(p.start_date),
    },
  ];

  return (
    <section className="page active">
      <div className="pagehead">
        <div>
          <h1>Projects</h1>
          <div className="sub">All delivery projects you can access</div>
        </div>
        <div className="spacer" />
      </div>
      {error && <div className="help err" style={{ margin: "12px 0" }}>{error}</div>}
      {projects === null && !error ? (
        <div className="card card-pad loading-inline"><Spinner /> Loading projects…</div>
      ) : (
        <DataTable
          columns={columns}
          rows={projects ?? []}
          rowKey={(p) => p.id}
          rowHref={projectHref}
          searchPlaceholder="Search project name, account..."
          searchValue={(p) => `${p.id} ${p.name} ${accountName(p.account_id)}`}
        />
      )}
    </section>
  );
}
