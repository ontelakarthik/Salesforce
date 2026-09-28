"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import RoleOnly from "../RoleOnly";
import ClickableRow from "../ClickableRow";
import Badge, { type BadgeVariant } from "../Badge";
import Spinner from "../Spinner";
import { Icon, type IconName } from "../icons";
import NewAccountModal from "./NewAccountModal";
import NewOpportunityModal from "./NewOpportunityModal";
import LeadershipPanel from "./LeadershipPanel";
import { fetchGraceful, useApi } from "@/lib/api/client";
import { listAccounts, listOpportunities, type AccountOut, type OpportunityOut } from "@/lib/api/crm";
import { listAgreements, type AgreementOut } from "@/lib/api/contracts";
import { listBudgetConsumption } from "@/lib/api/delivery";
import { listNotifications, type NotificationOut } from "@/lib/api/activity";
import { useAppSelector } from "@/lib/hooks";

interface StatCard {
  key: string;
  label: string;
  displayValue: string;
  detail: string;
  icon: IconName;
  iconBg: string;
  iconColor: string;
  redWhenPositive?: boolean;
  href: string;
}

interface ActionItem {
  id: string;
  account: string;
  type: string;
  typeVariant: BadgeVariant;
  status: string;
  statusVariant: BadgeVariant;
  due: string;
  /** 0 = breached, 1 = budget over cap, 2 = expiring soon, 3 = hot deal */
  urgency: number;
  href: string;
}

interface AlertItem {
  id: string;
  title: string;
  detail: string;
  severity: string;
  done: boolean;
}

const TYPE_BADGE: Record<string, BadgeVariant> = {
  NDA: "blue",
  MSA: "blue",
  SOW: "violet",
  VENDOR_MSA: "blue",
  PURCHASE_ORDER: "gray",
};

const SEVERITY_COLOR: Record<string, string> = {
  CRITICAL: "var(--red)",
  WARNING: "var(--amber)",
  WARN: "var(--amber)",
  INFO: "var(--ink)",
};

const THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000;

function formatMoney(value: number): string {
  if (Math.abs(value) >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`;
  if (Math.abs(value) >= 1_000) return `$${(value / 1000).toFixed(0)}K`;
  return `$${value.toLocaleString()}`;
}

function formatRelativePast(value: string | null): string {
  if (!value) return "—";
  const diffMs = Date.now() - new Date(value).getTime();
  const hours = Math.round(diffMs / (60 * 60 * 1000));
  if (hours < 1) return "just now";
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

function formatRelativeFuture(value: string): string {
  const days = Math.max(0, Math.round((new Date(value).getTime() - Date.now()) / (24 * 60 * 60 * 1000)));
  return `${days} day${days === 1 ? "" : "s"}`;
}

function formatShortDate(value: string): string {
  return new Date(value).toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
}

function humanize(code: string): string {
  return code
    .split("_")
    .map((word) => (word === "SLA" ? "SLA" : word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()))
    .join(" ");
}

function greetingWord(now: Date): string {
  const hour = now.getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

/** The company-wide view — Dashboard.tsx routes here only for a profile
 * holding manager_dashboard.read (LEADERSHIP/ADMIN by default). Everyone
 * else gets RepDashboard.tsx instead. This is today's original dashboard,
 * unchanged, just relocated out of the top-level switcher. */
export default function ManagerDashboard() {
  const api = useApi();
  const router = useRouter();
  const employee = useAppSelector((state) => state.auth.employee);
  const greetingName = employee?.full_name ?? employee?.email ?? "there";

  const [showNewAccount, setShowNewAccount] = useState(false);
  const [showNewOpportunity, setShowNewOpportunity] = useState(false);

  const [opportunities, setOpportunities] = useState<OpportunityOut[]>([]);
  const [opportunitiesForbidden, setOpportunitiesForbidden] = useState(false);
  const [agreements, setAgreements] = useState<AgreementOut[]>([]);
  const [agreementsForbidden, setAgreementsForbidden] = useState(false);
  const [accounts, setAccounts] = useState<Record<string, AccountOut>>({});
  const [notifications, setNotifications] = useState<NotificationOut[]>([]);
  const [sowConsumedPct, setSowConsumedPct] = useState<Record<string, number>>({});
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // `new Date()` differs between the server-rendered shell and the client's
  // first paint, which React flags as a hydration mismatch — compute it only
  // after mount instead of during render.
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
  }, []);

  // Each source is fetched independently (rather than one Promise.all that
  // fails as soon as any single request 403s) so a profile missing one
  // capability still gets everything else instead of the whole dashboard
  // going blank with a raw backend error — a forbidden source just
  // contributes nothing to the stats/action items built from it below,
  // instead of an error being shown about it.
  useEffect(() => {
    let cancelled = false;
    setLoaded(false);
    setError(null);
    Promise.all([
      fetchGraceful(listOpportunities(api)),
      fetchGraceful(listAgreements(api)),
      fetchGraceful(listAccounts(api, { page_size: 100 })),
      fetchGraceful(listNotifications(api)),
    ]).then(async ([oppsRes, agrsRes, accountsRes, notifsRes]) => {
      if (cancelled) return;
      setOpportunities(oppsRes.ok ? oppsRes.value : []);
      setOpportunitiesForbidden(!oppsRes.ok && oppsRes.forbidden);
      setAgreements(agrsRes.ok ? agrsRes.value : []);
      setAgreementsForbidden(!agrsRes.ok && agrsRes.forbidden);
      setAccounts(accountsRes.ok ? Object.fromEntries(accountsRes.value.items.map((c) => [c.id, c])) : {});
      setNotifications(notifsRes.ok ? notifsRes.value : []);
      const realError = [oppsRes, agrsRes, accountsRes, notifsRes].find((r) => !r.ok && !r.forbidden);
      setError(realError && !realError.ok && !realError.forbidden ? realError.message : null);

      const consumptions = await listBudgetConsumption(api).catch(() => []);
      if (cancelled) return;
      const map: Record<string, number> = {};
      consumptions.forEach((c) => {
        if (c.consumed_percent != null) map[c.agreement_id] = c.consumed_percent;
      });
      setSowConsumedPct(map);
      setLoaded(true);
    });
    return () => {
      cancelled = true;
    };
  }, [api]);

  function accountName(accountId: string | null): string {
    if (!accountId) return "—";
    return accounts[accountId]?.legal_name?.replace(/ Pvt\. Ltd\.$/, "") ?? accountId;
  }

  const openOpportunities = opportunities.filter((o) => o.stage !== "WON" && o.stage !== "LOST");
  const openPipelineValue = openOpportunities.reduce((sum, o) => sum + (o.estimated_value ?? 0), 0);
  const slaBreached = agreements.filter((a) => a.sla_breached_at);
  const budgetOver70Count = Object.values(sowConsumedPct).filter((p) => p >= 70).length;
  const expiringSoon = agreements.filter((a) => {
    if (!a.expiry_date) return false;
    const t = new Date(a.expiry_date).getTime();
    return t >= Date.now() && t <= Date.now() + THIRTY_DAYS_MS;
  });

  const stats: StatCard[] = [
    ...(opportunitiesForbidden ? [] : [{
      key: "open_pipeline_value",
      label: "Open pipeline",
      displayValue: formatMoney(openPipelineValue),
      detail: `across ${openOpportunities.length} deal${openOpportunities.length === 1 ? "" : "s"} · open`,
      icon: "trendingUp" as const,
      iconBg: "var(--primary-soft)",
      iconColor: "var(--primary)",
      href: "/opportunities",
    }]),
    ...(agreementsForbidden ? [] : [
      {
        key: "sla_breaches",
        label: "Agreements breaching SLA",
        displayValue: String(slaBreached.length),
        detail: "past their SLA window",
        icon: "alertTriangle" as const,
        iconBg: "var(--red-soft)",
        iconColor: "var(--red)",
        redWhenPositive: true,
        href: "/agreements",
      },
      {
        key: "budgets_over_70",
        label: "Budgets over 70%",
        displayValue: String(budgetOver70Count),
        detail: "SOWs nearing cap",
        icon: "dollar" as const,
        iconBg: "var(--amber-soft)",
        iconColor: "var(--amber)",
        href: "/agreements",
      },
      {
        key: "expiring_30d",
        label: "Expiring in 30 days",
        displayValue: String(expiringSoon.length),
        detail: "agreements to renew",
        icon: "calendar" as const,
        iconBg: "var(--teal-soft)",
        iconColor: "var(--teal)",
        href: "/agreements",
      },
    ]),
  ];

  const actionItems: ActionItem[] = [];
  for (const a of slaBreached) {
    actionItems.push({
      id: a.id,
      account: accountName(a.account_id),
      type: a.agreement_type,
      typeVariant: TYPE_BADGE[a.agreement_type] ?? "gray",
      status: "SLA breached",
      statusVariant: "red",
      due: formatRelativePast(a.sla_breached_at),
      urgency: 0,
      href: `/agreements/${a.id}`,
    });
  }
  for (const a of agreements) {
    const pct = sowConsumedPct[a.id];
    if (pct != null && pct >= 70) {
      actionItems.push({
        id: a.id,
        account: accountName(a.account_id),
        type: "SOW",
        typeVariant: "violet",
        status: `Budget ${Math.round(pct)}%`,
        statusVariant: "amber",
        due: "Review",
        urgency: 1,
        href: `/agreements/${a.id}`,
      });
    }
  }
  for (const a of expiringSoon) {
    if (a.sla_breached_at) continue;
    actionItems.push({
      id: a.id,
      account: accountName(a.account_id),
      type: a.agreement_type,
      typeVariant: TYPE_BADGE[a.agreement_type] ?? "gray",
      status: "Expiring soon",
      statusVariant: "amber",
      due: formatRelativeFuture(a.expiry_date as string),
      urgency: 2,
      href: `/agreements/${a.id}`,
    });
  }
  for (const o of opportunities.filter((o) => o.stage === "NEGOTIATION")) {
    actionItems.push({
      id: o.id,
      account: accountName(o.account_id),
      type: "Deal",
      typeVariant: "teal",
      status: "Negotiation",
      statusVariant: "blue",
      due: o.expected_close_date ? `Close ${formatShortDate(o.expected_close_date)}` : "—",
      urgency: 3,
      href: `/opportunities/${o.id}`,
    });
  }
  actionItems.sort((a, b) => a.urgency - b.urgency);
  const visibleActionItems = actionItems.slice(0, 8);

  const alerts: AlertItem[] = [...notifications]
    .sort((a, b) => Date.parse(b.sent_at) - Date.parse(a.sent_at))
    .slice(0, 6)
    .map((n) => ({
      id: n.id,
      title: `${humanize(n.notification_type)}${n.account_id ? ` · ${accountName(n.account_id)}` : n.agreement_id ? ` · ${n.agreement_id}` : ""}`,
      detail: formatRelativePast(n.sent_at),
      severity: n.severity,
      done: n.acknowledged,
    }));

  return (
    <section className="page active">
      <div className="pagehead">
        <div>
          <h1>{now ? greetingWord(now) : "Hello"}, {greetingName}</h1>
          <div className="sub">
            What needs your attention
            {now && ` — ${now.toLocaleDateString("en-US", { weekday: "long", day: "numeric", month: "long", year: "numeric" })}`}
          </div>
        </div>
        <div className="spacer" />
        <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
          <button className="btn" onClick={() => setShowNewAccount(true)}>
            <Icon name="plus" />
            New account
          </button>
        </RoleOnly>
        <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
          <button className="btn primary" onClick={() => setShowNewOpportunity(true)}>
            <Icon name="trendingUp" />
            New opportunity
          </button>
        </RoleOnly>
      </div>

      {error && <div className="help err" style={{ margin: "12px 0" }}>{error}</div>}

      <LeadershipPanel />

      {!loaded ? (
        <div className="card card-pad loading-inline"><Spinner /> Loading dashboard…</div>
      ) : (
        <>
          <div className="grid stats" style={{ marginBottom: 20 }}>
            {stats.map((s) => {
              const numeralColor = s.redWhenPositive && s.displayValue !== "0" ? "var(--red)" : "var(--ink)";
              return (
                <Link key={s.key} href={s.href} className="stat" style={{ cursor: "pointer" }}>
                  <div className="ic" style={{ background: s.iconBg, color: s.iconColor }}>
                    <Icon name={s.icon} />
                  </div>
                  <div className="k">{s.label}</div>
                  <div className="v" style={{ color: numeralColor }}>{s.displayValue}</div>
                  <div className="d">{s.detail}</div>
                </Link>
              );
            })}
          </div>

          <div className="split">
            <div className="card">
              <div className="card-head">
                <h3>Needs your action</h3>
                <div className="spacer" />
                <Badge variant="gray">{actionItems.length} items</Badge>
                <Link href="/agreements" className="btn sm">
                  View all
                </Link>
              </div>
              <div className="tablescroll">
                <table>
                  <thead>
                    <tr>
                      <th>Item</th>
                      <th>Account</th>
                      <th>Type</th>
                      <th>Status</th>
                      <th>Due</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleActionItems.map((item) => (
                      <ClickableRow key={item.id} href={item.href}>
                        <td className="t-strong">{item.id}</td>
                        <td>{item.account}</td>
                        <td><Badge variant={item.typeVariant} dot>{item.type}</Badge></td>
                        <td><Badge variant={item.statusVariant}>{item.status}</Badge></td>
                        <td className="t-muted">{item.due}</td>
                      </ClickableRow>
                    ))}
                    {visibleActionItems.length === 0 && (
                      <tr><td colSpan={5} className="empty-hint" style={{ padding: "18px 22px" }}>Nothing needs attention right now.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="card">
              <div className="card-head">
                <h3>Recent alerts</h3>
              </div>
              <div className="card-pad" style={{ paddingTop: 10 }}>
                <div className="timeline">
                  {alerts.map((a) => (
                    <div key={a.id} className={`tl-item${a.done ? " done" : ""}`}>
                      <div className="tl-t" style={{ color: SEVERITY_COLOR[a.severity] ?? "var(--ink)" }}>{a.title}</div>
                      <div className="tl-d">{a.detail}</div>
                    </div>
                  ))}
                  {alerts.length === 0 && <div className="t-muted" style={{ fontSize: 13 }}>No recent alerts.</div>}
                </div>
                <Link href="/notifications" className="btn sm" style={{ marginTop: 4 }}>
                  View all
                </Link>
              </div>
            </div>
          </div>
        </>
      )}

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
