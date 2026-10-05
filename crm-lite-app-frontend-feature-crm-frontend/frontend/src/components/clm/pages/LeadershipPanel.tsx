"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Badge from "../Badge";
import Spinner from "../Spinner";
import { ApiError, fetchGraceful, useApi } from "@/lib/api/client";
import { useEmployeeDirectory } from "@/lib/api/identity";
import { flagLeadHot, listLeads, type LeadOut } from "@/lib/api/crm";
import { getManagerDashboard, type ManagerDashboardOut } from "@/lib/api/platform";
import { STATUS_BADGE, STATUS_LABEL, leadFullName } from "./leadShared";

function repName(employeeLabel: (id: string | null) => string, ownerId: string | null): string {
  return ownerId ? employeeLabel(ownerId) : "Unassigned";
}

export default function LeadershipPanel() {
  const api = useApi();
  const { label: employeeLabel } = useEmployeeDirectory();
  const [summary, setSummary] = useState<ManagerDashboardOut | null>(null);
  const [summaryForbidden, setSummaryForbidden] = useState(false);
  const [leads, setLeads] = useState<LeadOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flaggingId, setFlaggingId] = useState<string | null>(null);
  const [flagError, setFlagError] = useState<string | null>(null);

  // Fetched independently (not one Promise.all) so a profile that somehow
  // holds manager_dashboard.read without also holding leads.read doesn't
  // get a raw backend error for the whole panel — just quietly skips
  // whichever half it isn't permitted to see.
  useEffect(() => {
    let cancelled = false;
    setError(null);
    Promise.all([fetchGraceful(getManagerDashboard(api)), fetchGraceful(listLeads(api))])
      .then(([summaryRes, leadsRes]) => {
        if (cancelled) return;
        setSummary(summaryRes.ok ? summaryRes.value : null);
        setSummaryForbidden(!summaryRes.ok && summaryRes.forbidden);
        setLeads(leadsRes.ok ? leadsRes.value : []);
        const realError = [summaryRes, leadsRes].find((r) => !r.ok && !r.forbidden);
        setError(realError && !realError.ok && !realError.forbidden ? realError.message : null);
      });
    return () => {
      cancelled = true;
    };
  }, [api]);

  function flagHot(lead: LeadOut) {
    setFlaggingId(lead.id);
    setFlagError(null);
    flagLeadHot(api, lead.id)
      .then((updated) => {
        setLeads((prev) => (prev ?? []).map((l) => (l.id === updated.id ? updated : l)));
      })
      .catch((err: unknown) => {
        setFlagError(err instanceof ApiError ? err.message : "Failed to flag lead as hot.");
      })
      .finally(() => setFlaggingId(null));
  }

  if (error) {
    return <div className="card card-pad help err" style={{ marginBottom: 20 }}>{error}</div>;
  }

  if (summaryForbidden) {
    return null;
  }

  if (!summary || !leads) {
    return <div className="card card-pad loading-inline" style={{ marginBottom: 20 }}><Spinner /> Loading team activity…</div>;
  }

  const activeLeads = leads
    .filter((l) => l.status !== "CONVERTED" && l.status !== "DISQUALIFIED" && l.status !== "UNQUALIFIED")
    .sort((a, b) => b.lead_score - a.lead_score)
    .slice(0, 8);

  const statusEntries = Object.entries(summary.leads_by_status).sort((a, b) => b[1] - a[1]);

  return (
    <>
      <div className="section-title">
        Team activity <span className="line" />
      </div>
      <div className="grid stats" style={{ marginBottom: 20 }}>
        <div className="stat">
          <div className="k">Leads created</div>
          <div className="v">{summary.team_totals.leads_created}</div>
        </div>
        <div className="stat">
          <div className="k">Leads qualified</div>
          <div className="v">{summary.team_totals.leads_qualified}</div>
        </div>
        <div className="stat">
          <div className="k">Closed Won</div>
          <div className="v">{summary.team_totals.leads_converted}</div>
        </div>
        <div className="stat">
          <div className="k">Conversion rate</div>
          <div className="v">{summary.conversion_rate_percent != null ? `${summary.conversion_rate_percent}%` : "—"}</div>
        </div>
        <div className="stat">
          <div className="k">Hot leads (score ≥ 50)</div>
          <div className="v">{summary.hot_lead_count}</div>
        </div>
        <div className="stat">
          <div className="k">Contacted leads</div>
          <div className="v">{summary.team_totals.leads_contacted}</div>
        </div>
        <div className="stat">
          <div className="k">Responded leads</div>
          <div className="v">{summary.team_totals.leads_responded}</div>
        </div>
      </div>

      <div className="split" style={{ marginBottom: 20 }}>
        <div className="card">
          <div className="card-head"><h3>Rep leaderboard</h3></div>
          <table>
            <thead><tr><th>Rep</th><th>Leads</th><th>Qualified</th><th>Closed Won</th><th>Emails</th><th>Calls</th></tr></thead>
            <tbody>
              {summary.leaderboard.map((r) => (
                <tr key={r.owner_employee_id ?? "unassigned"}>
                  <td style={{ whiteSpace: "nowrap" }}>{repName(employeeLabel, r.owner_employee_id)}</td>
                  <td className="num">{r.leads_created}</td>
                  <td className="num">{r.leads_qualified}</td>
                  <td className="num">{r.leads_converted}</td>
                  <td className="num">{r.emails_sent}</td>
                  <td className="num">{r.calls_made}</td>
                </tr>
              ))}
              {summary.leaderboard.length === 0 && (
                <tr><td colSpan={6} className="empty-hint" style={{ padding: "18px 22px" }}>No activity yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="card">
          <div className="card-head"><h3>Leads by stage</h3></div>
          <div className="card-pad" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {statusEntries.map(([status, count]) => (
              <div key={status} style={{ display: "flex", justifyContent: "space-between" }}>
                <Badge variant={STATUS_BADGE[status] ?? "gray"}>{STATUS_LABEL[status] ?? status}</Badge>
                <span className="num t-strong">{count}</span>
              </div>
            ))}
            {statusEntries.length === 0 && <div className="empty-hint">No leads yet.</div>}
          </div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 20 }}>
        <div className="card-head">
          <h3>Active leads — flag what needs close attention</h3>
        </div>
        {flagError && <div className="help err" style={{ margin: "0 16px" }}>{flagError}</div>}
        <table>
          <thead><tr><th>Company</th><th>Contact</th><th>Owner</th><th>Stage</th><th>Score</th><th>Rating</th><th></th></tr></thead>
          <tbody>
            {activeLeads.map((l) => (
              <tr key={l.id}>
                <td className="t-strong"><Link href={`/leads/${l.id}`}>{l.company_name}</Link></td>
                <td>{leadFullName(l) || "—"}</td>
                <td>{repName(employeeLabel, l.owner_employee_id)}</td>
                <td><Badge variant={STATUS_BADGE[l.status] ?? "gray"}>{STATUS_LABEL[l.status] ?? l.status}</Badge></td>
                <td className="num">{l.lead_score}</td>
                <td>{l.rating === "HOT" ? <Badge variant="red">HOT</Badge> : l.rating || "—"}</td>
                <td style={{ textAlign: "right" }}>
                  {l.rating === "HOT" ? (
                    <span className="empty-hint">Flagged</span>
                  ) : (
                    <button className="btn sm" disabled={flaggingId === l.id} onClick={() => flagHot(l)}>
                      {flaggingId === l.id ? "Flagging…" : "Notify as hot"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {activeLeads.length === 0 && (
              <tr><td colSpan={7} className="empty-hint" style={{ padding: "18px 22px" }}>No active leads.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
