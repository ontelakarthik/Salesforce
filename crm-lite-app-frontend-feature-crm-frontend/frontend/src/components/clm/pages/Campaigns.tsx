"use client";

import { useEffect, useState } from "react";
import RoleOnly from "../RoleOnly";
import Badge from "../Badge";
import DataTable, { type DataTableColumn } from "../DataTable";
import Spinner from "../Spinner";
import { Icon } from "../icons";
import { ApiError, useApi } from "@/lib/api/client";
import { deleteCampaign, listCampaigns, type CampaignOut } from "@/lib/api/crm";
import NewCampaignModal from "./NewCampaignModal";
import EditCampaignModal from "./EditCampaignModal";
import SendCampaignEmailModal from "./SendCampaignEmailModal";

export default function Campaigns() {
  const api = useApi();
  const [campaigns, setCampaigns] = useState<CampaignOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [sending, setSending] = useState<CampaignOut | null>(null);
  const [editing, setEditing] = useState<CampaignOut | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: fetch/reset state when inputs change
    setCampaigns(null);
    setError(null);
    listCampaigns(api)
      .then((rows) => {
        if (!cancelled) setCampaigns(rows);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Failed to load campaigns.");
      });
    return () => {
      cancelled = true;
    };
  }, [api]);

  function remove(campaign: CampaignOut) {
    if (!window.confirm(`Delete the campaign "${campaign.name}"? This can't be undone.`)) return;
    setDeletingId(campaign.id);
    setError(null);
    deleteCampaign(api, campaign.id)
      .then(() => setCampaigns((prev) => (prev ?? []).filter((c) => c.id !== campaign.id)))
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Failed to delete campaign.");
      })
      .finally(() => setDeletingId(null));
  }

  const columns: DataTableColumn<CampaignOut>[] = [
    {
      key: "name",
      label: "Name",
      sortable: true,
      sortValue: (c) => c.name,
      render: (c) => <span className="t-strong">{c.name}</span>,
    },
    {
      key: "type",
      label: "Type",
      sortable: true,
      sortValue: (c) => c.campaign_type ?? "",
      render: (c) => (c.campaign_type ? <Badge variant="blue">{c.campaign_type}</Badge> : "—"),
    },
    {
      key: "start",
      label: "Start",
      sortable: true,
      sortValue: (c) => (c.start_date ? Date.parse(c.start_date) : 0),
      render: (c) => (c.start_date ? new Date(c.start_date).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "—"),
    },
    {
      key: "end",
      label: "End",
      sortable: true,
      sortValue: (c) => (c.end_date ? Date.parse(c.end_date) : 0),
      render: (c) => (c.end_date ? new Date(c.end_date).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "—"),
    },
    {
      key: "status",
      label: "Status",
      sortable: true,
      sortValue: (c) => (c.is_active ? 1 : 0),
      render: (c) => <Badge variant={c.is_active ? "green" : "gray"}>{c.is_active ? "Active" : "Inactive"}</Badge>,
    },
    {
      key: "num_sent",
      label: "Emails sent",
      sortable: true,
      sortValue: (c) => c.num_sent ?? 0,
      render: (c) => c.num_sent ?? 0,
    },
    {
      key: "actions",
      label: "",
      render: (c) => (
        <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
          <div style={{ display: "flex", gap: 6, justifyContent: "flex-end", flexWrap: "wrap" }}>
            <button className="btn sm" onClick={() => setSending(c)}>Send email</button>
            {c.can_edit && (
              <button className="btn sm" onClick={() => setEditing(c)}>Edit</button>
            )}
            {c.can_delete && (
              <button className="btn sm" disabled={deletingId === c.id} onClick={() => remove(c)}>
                {deletingId === c.id ? "Deleting…" : "Delete"}
              </button>
            )}
          </div>
        </RoleOnly>
      ),
    },
  ];

  return (
    <section className="page active">
      <div className="pagehead">
        <div>
          <h1>Campaigns</h1>
          <div className="sub">Where your leads come from</div>
        </div>
        <div className="spacer" />
        <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
          <button className="btn primary" onClick={() => setShowNew(true)}>
            <Icon name="plus" />
            New campaign
          </button>
        </RoleOnly>
      </div>
      {error && <div className="help err" style={{ margin: "12px 0" }}>{error}</div>}
      {campaigns === null && !error ? (
        <div className="card card-pad loading-inline"><Spinner /> Loading campaigns…</div>
      ) : (
        <DataTable
          columns={columns}
          rows={campaigns ?? []}
          rowKey={(c) => c.id}
          searchPlaceholder="Search campaign name..."
          searchValue={(c) => `${c.name} ${c.campaign_type ?? ""}`}
        />
      )}
      <NewCampaignModal
        open={showNew}
        onClose={() => setShowNew(false)}
        onCreated={(created) => setCampaigns((prev) => (prev ? [created, ...prev] : [created]))}
      />
      <EditCampaignModal
        campaign={editing}
        onClose={() => setEditing(null)}
        onSaved={(updated) => setCampaigns((prev) => (prev ?? []).map((c) => (c.id === updated.id ? updated : c)))}
      />
      <SendCampaignEmailModal
        campaign={sending}
        onClose={() => setSending(null)}
        onSent={(campaignId, result) =>
          setCampaigns((prev) =>
            (prev ?? []).map((c) => (c.id === campaignId ? { ...c, num_sent: (c.num_sent ?? 0) + result.sent } : c))
          )
        }
      />
    </section>
  );
}
