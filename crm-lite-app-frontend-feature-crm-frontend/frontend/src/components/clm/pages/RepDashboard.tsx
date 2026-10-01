"use client";

import { useEffect, useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import ClickableRow from "../ClickableRow";
import Badge from "../Badge";
import Spinner from "../Spinner";
import { Icon, type IconName } from "../icons";
import NewLeadModal from "./NewLeadModal";
import NewAccountModal from "./NewAccountModal";
import NewOpportunityModal from "./NewOpportunityModal";
import { leadFullName, STATUS_BADGE, STATUS_LABEL } from "./leadShared";
import { ApiError, fetchGraceful, useApi } from "@/lib/api/client";
import { listLeads, listOpportunities, listCampaigns, type LeadOut, type OpportunityOut, type CampaignOut } from "@/lib/api/crm";
import {
  listMyCadenceTasks, completeCadenceTask, skipCadenceTask, type CadenceTaskOut,
} from "@/lib/api/cadence";
import { listNotifications, type NotificationOut } from "@/lib/api/activity";
import { useAppSelector } from "@/lib/hooks";

function formatRelativePast(value: string): string {
  const diffMs = Date.now() - new Date(value).getTime();
  const hours = Math.round(diffMs / (60 * 60 * 1000));
  if (hours < 1) return "just now";
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

function formatDueDate(value: string): string {
  const days = Math.round((new Date(value).getTime() - Date.now()) / (24 * 60 * 60 * 1000));
  if (days < 0) return `${Math.abs(days)}d overdue`;
  if (days === 0) return "Today";
  if (days === 1) return "Tomorrow";
  return new Date(value).toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
}

function greetingWord(now: Date): string {
  const hour = now.getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

interface StatCard {
  key: string;
  label: string;
  displayValue: string;
  icon: IconName;
  iconBg: string;
  iconColor: string;
  href: string;
}

/** The personal "my leads and my work" dashboard — what a SALES/ACCOUNT_EXEC
 * profile lands on now instead of the company-wide ManagerDashboard.
 * Everything here is already owner-scoped server-side (GET /leads and
 * GET /cadence-tasks/my both filter to rows this caller — or their Role
 * Hierarchy subordinates — actually own), so no client-side filtering by
 * owner is needed; this component just renders what the backend already
 * scoped correctly. */
export default function RepDashboard() {
  const api = useApi();
  const router = useRouter();
  const employee = useAppSelector((state) => state.auth.employee);
  const greetingName = employee?.full_name ?? employee?.email ?? "there";

  const [showNewLead, setShowNewLead] = useState(false);
  const [showNewAccount, setShowNewAccount] = useState(false);
  const [showNewOpportunity, setShowNewOpportunity] = useState(false);

  const [leads, setLeads] = useState<LeadOut[]>([]);
  const [opportunities, setOpportunities] = useState<OpportunityOut[]>([]);
  const [opportunitiesForbidden, setOpportunitiesForbidden] = useState(false);
  const [campaigns, setCampaigns] = useState<CampaignOut[]>([]);
  const [tasks, setTasks] = useState<CadenceTaskOut[]>([]);
  const [notifications, setNotifications] = useState<NotificationOut[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
  }, []);

  // Each widget's data is fetched independently (rather than one Promise.all
  // that fails as soon as any single request 403s) so a profile missing one
  // capability — e.g. SALES without opportunities.read — still gets its
  // leads, tasks and notifications instead of the whole dashboard going
  // blank with a raw backend error. A forbidden resource just renders as
  // quietly empty/hidden, matching how the rest of the app hides what a
  // profile isn't permitted to see instead of showing an error about it.
  function load() {
    let cancelled = false;
    setLoaded(false);
    setError(null);
    Promise.all([
      fetchGraceful(listLeads(api)),
      fetchGraceful(listOpportunities(api)),
      fetchGraceful(listCampaigns(api)),
      fetchGraceful(listMyCadenceTasks(api)),
      fetchGraceful(listNotifications(api)),
    ]).then(([leadsRes, oppsRes, campaignsRes, tasksRes, notifsRes]) => {
      if (cancelled) return;
      setLeads(leadsRes.ok ? leadsRes.value : []);
      setOpportunities(oppsRes.ok ? oppsRes.value : []);
      setOpportunitiesForbidden(!oppsRes.ok && oppsRes.forbidden);
      setCampaigns(campaignsRes.ok ? campaignsRes.value : []);
      setTasks(tasksRes.ok ? tasksRes.value : []);
      setNotifications(notifsRes.ok ? notifsRes.value : []);
      const realError = [leadsRes, oppsRes, campaignsRes, tasksRes, notifsRes]
        .find((r) => !r.ok && !r.forbidden);
      setError(realError && !realError.ok && !realError.forbidden ? realError.message : null);
      setLoaded(true);
    });
    return () => {
      cancelled = true;
    };
  }

  useEffect(load, [api]);

  function actOnTask(taskId: string, action: "complete" | "skip") {
    startTransition(async () => {
      try {
        if (action === "complete") await completeCadenceTask(api, taskId);
        else await skipCadenceTask(api, taskId);
        load();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to update task.");
      }
    });
  }

  const openLeads = leads.filter((l) => l.status !== "CONVERTED" && l.status !== "UNQUALIFIED" && l.status !== "DISQUALIFIED");
  const openOpportunities = opportunities.filter((o) => o.stage !== "WON" && o.stage !== "LOST");
  const unacknowledged = notifications.filter((n) => !n.acknowledged);

  const stats: StatCard[] = [
    {
      key: "my_leads", label: "My open leads", displayValue: String(openLeads.length),
      icon: "userCircle", iconBg: "var(--primary-soft)", iconColor: "var(--primary)", href: "/leads",
    },
    ...(opportunitiesForbidden ? [] : [{
      key: "my_opps", label: "My open opportunities", displayValue: String(openOpportunities.length),
      icon: "trendingUp" as const, iconBg: "var(--teal-soft)", iconColor: "var(--teal)", href: "/opportunities",
    }]),
    {
      key: "my_tasks", label: "Cadence tasks due", displayValue: String(tasks.length),
      icon: "clock", iconBg: "var(--amber-soft)", iconColor: "var(--amber)", href: "#my-tasks",
    },
    {
      key: "alerts", label: "Notifications", displayValue: String(unacknowledged.length),
      icon: "bell", iconBg: "var(--red-soft)", iconColor: "var(--red)", href: "/notifications",
    },
  ];

  const visibleLeads = [...openLeads].sort((a, b) => b.lead_score - a.lead_score).slice(0, 8);

  return (
    <section className="page active">
      <div className="pagehead">
        <div>
          <h1>{now ? greetingWord(now) : "Hello"}, {greetingName}</h1>
          <div className="sub">Your leads and what needs your attention today</div>
        </div>
        <div className="spacer" />
        <button className="btn" onClick={() => setShowNewAccount(true)}>
          <Icon name="plus" />
          New account
        </button>
        <button className="btn" onClick={() => setShowNewOpportunity(true)}>
          <Icon name="trendingUp" />
          New opportunity
        </button>
        <button className="btn primary" onClick={() => setShowNewLead(true)}>
          <Icon name="plus" />
          New lead
        </button>
      </div>

      {error && <div className="help err" style={{ margin: "12px 0" }}>{error}</div>}

      {!loaded ? (
        <div className="card card-pad loading-inline"><Spinner /> Loading your dashboard…</div>
      ) : (
        <>
          <div className="grid stats" style={{ marginBottom: 20 }}>
            {stats.map((s) => (
              <Link key={s.key} href={s.href} className="stat" style={{ cursor: "pointer" }}>
                <div className="ic" style={{ background: s.iconBg, color: s.iconColor }}>
                  <Icon name={s.icon} />
                </div>
                <div className="k">{s.label}</div>
                <div className="v">{s.displayValue}</div>
              </Link>
            ))}
          </div>

          <div className="split">
            <div className="card">
              <div className="card-head">
                <h3>My leads</h3>
                <div className="spacer" />
                <Badge variant="gray">{openLeads.length} open</Badge>
                <Link href="/leads" className="btn sm">View all</Link>
              </div>
              <div className="tablescroll">
                <table>
                  <thead>
                    <tr><th>Company</th><th>Contact</th><th>Status</th><th>Rating</th></tr>
                  </thead>
                  <tbody>
                    {visibleLeads.map((l) => (
                      <ClickableRow key={l.id} href={`/leads/${l.id}`}>
                        <td className="t-strong">{l.company_name ?? "—"}</td>
                        <td>{leadFullName(l) || "—"}</td>
                        <td><Badge variant={STATUS_BADGE[l.status] ?? "gray"}>{STATUS_LABEL[l.status] ?? l.status}</Badge></td>
                        <td>{l.rating === "HOT" ? <Badge variant="red">HOT</Badge> : l.rating || "—"}</td>
                      </ClickableRow>
                    ))}
                    {visibleLeads.length === 0 && (
                      <tr><td colSpan={4} className="empty-hint" style={{ padding: "18px 22px" }}>No open leads right now.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="card" id="my-tasks">
              <div className="card-head">
                <h3>My cadence tasks</h3>
                <div className="spacer" />
                <Badge variant="gray">{tasks.length} due</Badge>
              </div>
              <div className="tablescroll">
                <table>
                  <thead>
                    <tr><th>Due</th><th>Lead</th><th>Step</th><th></th></tr>
                  </thead>
                  <tbody>
                    {tasks.map((t) => (
                      <tr key={t.id}>
                        <td className="t-muted">{formatDueDate(t.due_date)}</td>
                        <td><Link href={`/leads/${t.lead_id}`}>{t.subject}</Link></td>
                        <td><Badge variant="gray">{t.step_type}</Badge></td>
                        <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                          <button className="btn sm" disabled={isPending} onClick={() => actOnTask(t.id, "complete")}>Complete</button>{" "}
                          <button className="btn sm" disabled={isPending} onClick={() => actOnTask(t.id, "skip")}>Skip</button>
                        </td>
                      </tr>
                    ))}
                    {tasks.length === 0 && (
                      <tr><td colSpan={4} className="empty-hint" style={{ padding: "18px 22px" }}>No cadence tasks due.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <div className="card" style={{ marginTop: 20 }}>
            <div className="card-head">
              <h3>Recent alerts</h3>
            </div>
            <div className="card-pad" style={{ paddingTop: 10 }}>
              <div className="timeline">
                {[...notifications]
                  .sort((a, b) => Date.parse(b.sent_at) - Date.parse(a.sent_at))
                  .slice(0, 6)
                  .map((n) => (
                    <div key={n.id} className={`tl-item${n.acknowledged ? " done" : ""}`}>
                      <div className="tl-t">{n.message ?? n.notification_type}</div>
                      <div className="tl-d">{formatRelativePast(n.sent_at)}</div>
                    </div>
                  ))}
                {notifications.length === 0 && <div className="t-muted" style={{ fontSize: 13 }}>No recent alerts.</div>}
              </div>
              <Link href="/notifications" className="btn sm" style={{ marginTop: 4 }}>View all</Link>
            </div>
          </div>
        </>
      )}

      <NewLeadModal
        open={showNewLead}
        campaigns={campaigns}
        onClose={() => setShowNewLead(false)}
        onCreated={(created) => router.push(`/leads/${created.id}`)}
      />
      <NewAccountModal
        open={showNewAccount}
        onClose={() => setShowNewAccount(false)}
        onCreated={(created, andNew) => {
          if (!andNew) router.push(`/accounts/${created.id}`);
        }}
      />
      <NewOpportunityModal
        open={showNewOpportunity}
        onClose={() => setShowNewOpportunity(false)}
        onCreated={(created, andNew) => {
          if (!andNew) router.push(`/opportunities/${created.id}`);
        }}
      />
    </section>
  );
}
