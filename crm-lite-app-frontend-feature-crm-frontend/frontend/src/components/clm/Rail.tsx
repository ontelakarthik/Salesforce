"use client";

import { Icon, type IconName } from "./icons";
import BrandMark from "./BrandMark";
import type { AppId } from "./apps";
import { useAppSelector } from "@/lib/hooks";

const RAIL_ITEMS_BY_APP: Record<AppId, { group: string; label: string; icon: IconName }[]> = {
  CLM: [
    { group: "home", label: "Home", icon: "grid" },
    { group: "workspace", label: "Workspace", icon: "building" },
    { group: "agreements", label: "Agreements", icon: "document" },
    { group: "delivery", label: "Delivery", icon: "clock" },
  ],
  CRM_LITE: [
    { group: "home", label: "Home", icon: "grid" },
    { group: "workspace", label: "Workspace", icon: "building" },
  ],
};

export default function Rail({
  activeGroup,
  onGroupClick,
  onBrandClick,
  showBrand,
}: {
  activeGroup: string;
  onGroupClick: (group: string) => void;
  onBrandClick: () => void;
  showBrand: boolean;
}) {
  const role = useAppSelector((state) => state.role.value);
  const appId = useAppSelector((state) => state.app.value);
  return (
    <aside className="rail">
      {showBrand && (
        <button className="rail-brand" onClick={onBrandClick} title="Open panel" aria-label="Open panel">
          <BrandMark fill="#1C2A3A" />
        </button>
      )}
      {RAIL_ITEMS_BY_APP[appId].map((item) => (
        <a
          key={item.group}
          className={`rail-item${activeGroup === item.group ? " active" : ""}`}
          title={item.label}
          onClick={() => onGroupClick(item.group)}
        >
          <span className="ic-wrap">
            <Icon name={item.icon} />
          </span>
          {item.label}
        </a>
      ))}
      {role === "ADMIN" && (
        <a
          className={`rail-item${activeGroup === "admin" ? " active" : ""}`}
          title="Admin"
          onClick={() => onGroupClick("admin")}
        >
          <span className="ic-wrap">
            <Icon name="layers" />
          </span>
          Admin
        </a>
      )}
      <a className="rail-item rail-help" title="Help">
        <span className="ic-wrap">
          <Icon name="help" />
        </span>
        Help
      </a>
    </aside>
  );
}
