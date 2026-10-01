"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import AccessDenied from "../AccessDenied";
import RoleOnly from "../RoleOnly";
import Badge from "../Badge";
import DataTable, { TableLink, type DataTableColumn } from "../DataTable";
import Spinner from "../Spinner";
import { Icon } from "../icons";
import { ApiError, useApi } from "@/lib/api/client";
import { deleteLead, listCampaigns, listLeads, updateLead, type CampaignOut, type LeadOut } from "@/lib/api/crm";
import NewLeadModal from "./NewLeadModal";
import ConvertLeadModal from "./ConvertLeadModal";
import { ACTION_LABEL, LEAD_TRANSITIONS, STATUS_BADGE, STATUS_DESCRIPTION, STATUS_LABEL, leadFullName } from "./leadShared";

function leadHref(lead: LeadOut): string {
  return `/leads/${lead.id}`;
}

export default function Leads() {
  const api = useApi();
  const [leads, setLeads] = useState<LeadOut[] | null>(null);
  const [campaigns, setCampaigns] = useState<Record<string, CampaignOut>>({});
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [converting, setConverting] = useState<LeadOut | null>(null);
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [rowError, setRowError] = useState<{ id: string; message: string } | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLeads(null);
    setError(null);
    setForbidden(false);
    Promise.all([listLeads(api), listCampaigns(api)])
      .then(([leadRows, campaignRows]) => {
        if (cancelled) return;
        setLeads(leadRows);
        setCampaigns(Object.fromEntries(campaignRows.map((c) => [c.id, c])));
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.code === "FORBIDDEN") setForbidden(true);
        else setError(err instanceof ApiError ? err.message : "Failed to load leads.");
      });
    return () => {
      cancelled = true;
    };
  }, [api]);

  if (forbidden) return <AccessDenied what="Leads" />;

  async function advance(lead: LeadOut, status: string) {
    setUpdatingId(lead.id);
    setRowError(null);
    try {
      const updated = await updateLead(api, lead.id, { status });
      setLeads((prev) => prev?.map((l) => (l.id === updated.id ? updated : l)) ?? prev);
    } catch (err) {
      setRowError({ id: lead.id, message: err instanceof ApiError ? err.message : "Failed to update lead." });
    } finally {
      setUpdatingId(null);
    }
  }

  function remove(lead: LeadOut) {
    if (!window.confirm(`Delete the lead "${lead.company_name}"? This can't be undone.`)) return;
    setDeletingId(lead.id);
    setRowError(null);
    deleteLead(api, lead.id)
      .then(() => setLeads((prev) => (prev ?? []).filter((l) => l.id !== lead.id)))
      .catch((err: unknown) => {
        setRowError({ id: lead.id, message: err instanceof ApiError ? err.message : "Failed to delete lead." });
      })
      .finally(() => setDeletingId(null));
  }

  const columns: DataTableColumn<LeadOut>[] = [
    {
      key: "company",
      label: "Company",
      sortable: true,
      sortValue: (l) => l.company_name ?? "",
      render: (l) => <TableLink href={leadHref(l)}>{l.company_name}</TableLink>,
    },
    {
      key: "contact",
      label: "Contact",
      sortable: true,
      sortValue: (l) => leadFullName(l),
      render: (l) => leadFullName(l),
    },
    {
      key: "campaign",
      label: "Campaign",
      sortable: true,
      sortValue: (l) => (l.campaign_id ? campaigns[l.campaign_id]?.name ?? "" : ""),
      render: (l) => (l.campaign_id ? campaigns[l.campaign_id]?.name ?? l.campaign_id : "—"),
    },
    {
      key: "source",
      label: "Source",
      sortable: true,
      className: "t-muted",
      sortValue: (l) => l.source ?? "",
      render: (l) => l.source ?? "—",
    },
    {
      key: "status",
      label: "Status",
      sortable: true,
      sortValue: (l) => l.status,
      render: (l) => (
        <span title={STATUS_DESCRIPTION[l.status]}>
          <Badge variant={STATUS_BADGE[l.status] ?? "gray"}>{STATUS_LABEL[l.status] ?? l.status}</Badge>
        </span>
      ),
    },
    {
      key: "lead_score",
      label: "Score",
      sortable: true,
      className: "num",
      sortValue: (l) => l.lead_score,
      render: (l) => <span className="num">{l.lead_score}</span>,
    },
    {
      key: "actions",
      label: "",
      render: (l) => {
        const nextOptions = l.status === "CONVERTED" ? [] : LEAD_TRANSITIONS[l.status] ?? [];
        return (
          <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
            <div
              style={{ display: "flex", gap: 6, justifyContent: "flex-end", flexWrap: "wrap" }}
              onClick={(e) => e.stopPropagation()}
            >
              {l.status === "CONVERTED" && l.converted_account_id && (
                <Link href={`/accounts/${l.converted_account_id}`} className="btn sm">
                  View account
                </Link>
              )}
              {l.status === "CONVERTED" && l.converted_opportunity_id && (
                <Link href={`/opportunities/${l.converted_opportunity_id}`} className="btn sm">
                  View opportunity
                </Link>
              )}
              {l.status === "QUALIFIED" && (
                <button className="btn primary sm" disabled={updatingId === l.id} onClick={() => setConverting(l)}>
                  Convert
                </button>
              )}
              {nextOptions.map((next) => (
                <button
                  key={next}
                  className="btn sm"
                  disabled={updatingId === l.id}
                  onClick={() => advance(l, next)}
                >
                  {ACTION_LABEL[next] ?? next}
                </button>
              ))}
              {l.can_delete && (
                <button
                  className="btn sm"
                  disabled={deletingId === l.id}
                  onClick={() => remove(l)}
                >
                  {deletingId === l.id ? "Deleting…" : "Delete"}
                </button>
              )}
            </div>
            {rowError?.id === l.id && <div className="help err">{rowError.message}</div>}
          </RoleOnly>
        );
      },
    },
  ];

  return (
    <section className="page active">
      <div className="pagehead">
        <div>
          <h1>Leads</h1>
          <div className="sub">Front of the funnel — qualify, then convert</div>
        </div>
        <div className="spacer" />
        <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
          <button className="btn primary" onClick={() => setShowNew(true)}>
            <Icon name="plus" />
            New lead
          </button>
        </RoleOnly>
      </div>
      {error && <div className="help err" style={{ margin: "12px 0" }}>{error}</div>}
      {leads === null && !error ? (
        <div className="card card-pad loading-inline"><Spinner /> Loading leads…</div>
      ) : (
        <DataTable
          columns={columns}
          rows={leads ?? []}
          rowKey={(l) => l.id}
          rowHref={leadHref}
          searchPlaceholder="Search company, contact..."
          searchValue={(l) => `${l.company_name} ${leadFullName(l)} ${l.source ?? ""}`}
        />
      )}
      <NewLeadModal
        open={showNew}
        onClose={() => setShowNew(false)}
        onCreated={(created) => setLeads((prev) => (prev ? [created, ...prev] : [created]))}
        campaigns={Object.values(campaigns)}
      />
      <ConvertLeadModal
        lead={converting}
        onClose={() => setConverting(null)}
        onConverted={(converted) => {
          setLeads((prev) => prev?.map((l) => (l.id === converted.id ? converted : l)) ?? prev);
        }}
      />
    </section>
  );
}
