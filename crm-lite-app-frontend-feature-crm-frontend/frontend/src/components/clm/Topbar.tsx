"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Icon } from "./icons";
import Popover from "./Popover";
import { roleInfo, isHrefAllowedForRole } from "./data";
import type { Role } from "./data";
import { appInfo, isHrefAllowedForApp, type AppId } from "./apps";
import { useAppDispatch, useAppSelector } from "@/lib/hooks";
import { setRole as setRoleAction } from "@/lib/features/roleSlice";
import { setApp as setAppAction } from "@/lib/features/appSlice";
import { logout as logoutAction } from "@/lib/features/authSlice";
import { useApi } from "@/lib/api/client";
import { listNotifications, type NotificationOut } from "@/lib/api/activity";

function initialsOf(name: string | null, email: string | null): string {
  const source = name?.trim() || email || "";
  const parts = source.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return source.slice(0, 2).toUpperCase() || "?";
}

const ROLES: Role[] = ["SALES", "ACCOUNT_EXEC", "LEADERSHIP", "ADMIN"];
const ROLE_LABELS: Record<Role, string> = {
  SALES: "Sales",
  ACCOUNT_EXEC: "Account Exec",
  LEADERSHIP: "Leadership",
  ADMIN: "Admin",
};

function humanize(code: string): string {
  return code
    .split("_")
    .map((word) => (word === "SLA" ? "SLA" : word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()))
    .join(" ");
}

function timeAgo(sentAt: string): string {
  const ms = Date.now() - new Date(sentAt).getTime();
  const hours = Math.round(ms / (60 * 60 * 1000));
  if (hours < 1) return "just now";
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export default function Topbar() {
  const role = useAppSelector((state) => state.role.value);
  const appId = useAppSelector((state) => state.app.value);
  const employee = useAppSelector((state) => state.auth.employee);
  // Real RBAC now decides what this person can do (see authSlice/roleSlice's
  // sync on login) — this switcher only lets them pick among roles they
  // actually hold, never any of the other three, so it can no longer be used
  // to self-escalate to a role (e.g. Admin) they weren't granted.
  const grantedRoles = ROLES.filter((r) => employee?.roles.includes(r));
  const dispatch = useAppDispatch();
  const pathname = usePathname();
  const router = useRouter();
  const api = useApi();

  function handleLogout(close: () => void) {
    close();
    dispatch(logoutAction());
    router.replace("/login");
  }

  const [notifications, setNotifications] = useState<NotificationOut[]>([]);
  const unreadCount = notifications.filter((n) => !n.acknowledged).length;

  function refreshNotifications() {
    listNotifications(api)
      .then(setNotifications)
      .catch(() => {
        // The bell is a passive summary — a failed background refresh
        // shouldn't interrupt whatever page the user is on.
      });
  }

  useEffect(() => {
    refreshNotifications();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);

  function goToNotification(n: NotificationOut, close: () => void) {
    close();
    if (n.agreement_id) router.push(`/agreements/${n.agreement_id}`);
    else if (n.lead_id) router.push(`/leads/${n.lead_id}`);
    else if (n.account_id) router.push(`/accounts/${n.account_id}`);
    else router.push("/notifications");
  }

  function handleRoleChange(newRole: Role) {
    dispatch(setRoleAction(newRole));
    if (!isHrefAllowedForRole(pathname, newRole)) {
      router.push(roleInfo[newRole].land);
    }
  }

  function handleAppChange(newApp: AppId) {
    dispatch(setAppAction(newApp));
    if (!isHrefAllowedForApp(pathname, newApp)) {
      router.push(appInfo[newApp].land);
    }
  }

  return (
    <div className="topbar2">
      <Popover
        align="left"
        panelStyle={{ width: 260 }}
        trigger={({ toggle }) => (
          <button
            className="app-launcher-btn"
            title={`${appInfo[appId].label} — switch app`}
            onClick={toggle}
          >
            <Icon name="waffle" />
          </button>
        )}
      >
        {(close) => (
          <>
            <div className="am-label">Apps</div>
            <div className="launcher-grid">
              {(Object.keys(appInfo) as AppId[]).map((id) => (
                <button
                  key={id}
                  className={`launcher-tile${id === appId ? " on" : ""}`}
                  onClick={() => {
                    handleAppChange(id);
                    close();
                  }}
                >
                  <span className="ic">
                    <Icon name={appInfo[id].icon} />
                  </span>
                  <span className="lbl">{appInfo[id].label}</span>
                  <span className="sub">{appInfo[id].tagline}</span>
                </button>
              ))}
            </div>
          </>
        )}
      </Popover>
      <div className="searchbar">
        <Icon name="search" />
        Search…
      </div>
      <button className="adv-btn">Advanced Search</button>
      <div className="topicons">
        <Icon name="checkCircle" />
        <Popover
          trigger={({ toggle }) => (
            <div
              className="avatarwrap"
              onClick={() => {
                refreshNotifications();
                toggle();
              }}
            >
              <Icon name="bell" />
              {unreadCount > 0 && (
                <span
                  style={{
                    position: "absolute", top: -4, left: 10, minWidth: 15, height: 15, padding: "0 3px",
                    borderRadius: 8, background: "var(--red)", color: "#fff", fontSize: 10, fontWeight: 700,
                    display: "flex", alignItems: "center", justifyContent: "center", lineHeight: 1,
                  }}
                >
                  {unreadCount > 9 ? "9+" : unreadCount}
                </span>
              )}
            </div>
          )}
          panelStyle={{ width: 320 }}
        >
          {(close) => (
            <>
              <div className="am-label">Notifications</div>
              <div className="timeline" style={{ maxHeight: 320, overflowY: "auto", paddingRight: 2 }}>
                {notifications.slice(0, 6).map((n) => (
                  <div
                    key={n.id}
                    className={`tl-item${n.acknowledged ? " done" : ""}`}
                    style={{ cursor: "pointer" }}
                    onClick={() => goToNotification(n, close)}
                  >
                    <div className="tl-t">{n.message ?? humanize(n.notification_type)}</div>
                    <div className="tl-d">{timeAgo(n.sent_at)}</div>
                  </div>
                ))}
                {notifications.length === 0 && (
                  <div className="t-muted" style={{ fontSize: 13 }}>No notifications.</div>
                )}
              </div>
              <button
                className="btn sm"
                style={{ marginTop: 6, width: "100%" }}
                onClick={() => {
                  close();
                  router.push("/notifications");
                }}
              >
                View all
              </button>
            </>
          )}
        </Popover>
        <Popover
          trigger={({ toggle }) => (
            <div className="avatarwrap" onClick={toggle}>
              <div className="avatar">{initialsOf(employee?.full_name ?? null, employee?.email ?? null)}</div>
              <Icon name="chevronDown" />
            </div>
          )}
        >
          {(close) => (
            <>
              <div className="am-label">Signed in as</div>
              <div className="am-desc" style={{ marginBottom: 10 }}>
                <b>{employee?.full_name ?? "Unknown"}</b>
                <br />
                {employee?.email}
              </div>
              <button className="btn sm" style={{ width: "100%" }} onClick={() => handleLogout(close)}>
                Log out
              </button>
              {grantedRoles.length > 0 ? (
                <>
                  <div className="am-label" style={{ marginTop: 14 }}>Your role{grantedRoles.length > 1 ? "s" : ""}</div>
                  <div className="am-roles">
                    {grantedRoles.map((r) => (
                      <button
                        key={r}
                        className={r === role ? "on" : ""}
                        onClick={() => handleRoleChange(r)}
                      >
                        {ROLE_LABELS[r]}
                      </button>
                    ))}
                  </div>
                  <div className="am-desc">{roleInfo[role].text}</div>
                </>
              ) : (
                <div className="am-desc" style={{ marginTop: 14 }}>
                  No role assigned yet — contact an administrator.
                </div>
              )}
            </>
          )}
        </Popover>
      </div>
    </div>
  );
}
