"use client";

import { useEffect, useState, useTransition } from "react";
import Badge, { type BadgeVariant } from "../Badge";
import ClickableRow from "../ClickableRow";
import Spinner from "../Spinner";
import { ApiError, useApi } from "@/lib/api/client";
import { acknowledgeNotification, listNotifications, type NotificationOut } from "@/lib/api/activity";

const TYPE_BADGE: Record<string, BadgeVariant> = {
  SLA_REMINDER: "amber",
  SLA_BREACH: "red",
  BUDGET_THRESHOLD: "amber",
  MILESTONE_APPROACHING: "blue",
  EXPIRY_WARNING: "amber",
  AGREEMENT_PENDING_SIGNATURE: "amber",
  AGREEMENT_SIGNED: "green",
  LEAD_FLAGGED_HOT: "red",
};

const TYPE_LABEL: Record<string, string> = {
  SLA_REMINDER: "SLA reminder",
  SLA_BREACH: "SLA breach",
  BUDGET_THRESHOLD: "Budget threshold",
  MILESTONE_APPROACHING: "Milestone",
  EXPIRY_WARNING: "Expiring",
  AGREEMENT_PENDING_SIGNATURE: "Pending signature",
  AGREEMENT_SIGNED: "Signed",
  LEAD_FLAGGED_HOT: "Lead flagged hot",
};

/** The one entity id a notification links to, whichever type it is —
 * agreement/account/lead notifications each only ever set one of these. */
function relatedHref(n: NotificationOut): string | null {
  if (n.agreement_id) return `/agreements/${n.agreement_id}`;
  if (n.lead_id) return `/leads/${n.lead_id}`;
  if (n.account_id) return `/accounts/${n.account_id}`;
  return null;
}

function relatedLabel(n: NotificationOut): string {
  return n.agreement_id ?? n.lead_id ?? n.account_id ?? "—";
}

function timeAgo(sentAt: string): string {
  const ms = Date.now() - new Date(sentAt).getTime();
  const hours = Math.round(ms / (60 * 60 * 1000));
  if (hours < 1) return "just now";
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export default function Notifications() {
  const api = useApi();
  const [notifications, setNotifications] = useState<NotificationOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    let cancelled = false;
    setNotifications(null);
    setError(null);
    listNotifications(api)
      .then((rows) => {
        if (!cancelled) setNotifications(rows);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Failed to load notifications.");
      });
    return () => {
      cancelled = true;
    };
  }, [api]);

  function acknowledge(id: string) {
    startTransition(async () => {
      try {
        const updated = await acknowledgeNotification(api, id);
        setNotifications((prev) => (prev ? prev.map((n) => (n.id === id ? updated : n)) : prev));
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to acknowledge notification.");
      }
    });
  }

  return (
    <section className="page active">
      <div className="pagehead">
        <div>
          <h1>Notifications</h1>
          <div className="sub">SLA, budget, expiry, milestone and signature alerts</div>
        </div>
      </div>
      {error && <div className="help err" style={{ margin: "12px 0" }}>{error}</div>}
      {notifications === null && !error ? (
        <div className="card card-pad loading-inline"><Spinner /> Loading notifications…</div>
      ) : (
        <div className="card">
          <table>
            <thead><tr><th>Type</th><th>Message</th><th>Related</th><th>Sent</th><th></th></tr></thead>
            <tbody>
              {notifications?.map((n) => {
                const cells = (
                  <>
                    <td>
                      <Badge variant={TYPE_BADGE[n.notification_type] ?? "gray"}>
                        {TYPE_LABEL[n.notification_type] ?? n.notification_type}
                      </Badge>
                    </td>
                    <td>{n.message ?? "—"}</td>
                    <td className="mono" style={{ color: "var(--primary)" }}>{relatedLabel(n)}</td>
                    <td className="t-muted">{timeAgo(n.sent_at)}</td>
                    <td style={{ textAlign: "right" }}>
                      {n.acknowledged ? (
                        <Badge variant="green">Acknowledged</Badge>
                      ) : (
                        <button
                          className="btn sm"
                          disabled={isPending}
                          onClick={(e) => {
                            e.stopPropagation();
                            acknowledge(n.id);
                          }}
                        >
                          Acknowledge
                        </button>
                      )}
                    </td>
                  </>
                );
                const href = relatedHref(n);
                return href ? (
                  <ClickableRow key={n.id} href={href}>
                    {cells}
                  </ClickableRow>
                ) : (
                  <tr key={n.id}>{cells}</tr>
                );
              })}
              {notifications?.length === 0 && (
                <tr><td colSpan={5} className="empty-hint" style={{ padding: "18px 22px" }}>No notifications.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
