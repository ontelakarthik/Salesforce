"use client";

import Link from "next/link";
import { Icon } from "./icons";
import BrandMark from "./BrandMark";
import { appInfo } from "./apps";
import { navConfigForApp, groupTitles } from "./data";
import { useAppSelector } from "@/lib/hooks";

export default function Panel({
  activeGroup,
  pathname,
  onCollapse,
}: {
  activeGroup: string;
  pathname: string;
  onCollapse: () => void;
}) {
  const role = useAppSelector((state) => state.role.value);
  const appId = useAppSelector((state) => state.app.value);
  const permissions = useAppSelector((state) => state.auth.employee?.permissions);
  const title = groupTitles[activeGroup] ?? "";

  return (
    <aside className="panel">
      <div className="panel-brand">
        <BrandMark fill="#1C2A3A" />
        <div className="panel-brand-text">
          <span className="panel-brand-name">Tachyon Connect</span>
          <span className="panel-brand-app">{appInfo[appId].label}</span>
        </div>
      </div>
      <div className="panel-head">
        <span>{title}</span>
        <button className="panel-collapse" onClick={onCollapse}>
          ⮜
        </button>
      </div>
      {navConfigForApp(appId).map((g) => {
        if (g.roles && !g.roles.includes(role)) return null;
        return (
          <div
            key={g.group}
            className={`panel-group${activeGroup === g.group ? "" : " hidden"}`}
          >
            {g.items.map((item) => {
              if (item.roles && !item.roles.includes(role)) return null;
              // Real capability check (Object Permissions), separate from
              // the roles check above (the UI-only "viewing as" simulator)
              // — permissions is undefined only before the auth slice has
              // hydrated, in which case fail open rather than flash-hide.
              if (item.capability && permissions && !permissions.includes(item.capability)) return null;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`panel-item${pathname === item.href ? " active" : ""}`}
                >
                  <Icon name={item.icon} />
                  {item.label}
                  {item.href === "/timesheets" && (role === "ACCOUNT_EXEC" || role === "ADMIN") && (
                    <span
                      style={{
                        marginLeft: 4,
                        fontSize: 10,
                        background: "#B91C1C",
                        color: "#fff",
                        borderRadius: 20,
                        padding: "1px 7px",
                        fontWeight: 700,
                      }}
                    >
                      4
                    </span>
                  )}
                </Link>
              );
            })}
          </div>
        );
      })}
    </aside>
  );
}
