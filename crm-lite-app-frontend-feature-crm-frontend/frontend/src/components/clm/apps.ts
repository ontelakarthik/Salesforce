import type { IconName } from "./icons";

/** Tachyon Connect hosts multiple switchable "apps" (App Launcher pattern),
 * all reading/writing the same backend data — see data.ts's navConfig vs
 * crmLiteNavConfig for what each app's sidebar surfaces. */
export type AppId = "CLM" | "CRM_LITE";

export interface AppInfo {
  label: string;
  tagline: string;
  icon: IconName;
  /** Where this app lands when it can't show the current route. */
  land: string;
}

export const appInfo: Record<AppId, AppInfo> = {
  CLM: {
    label: "CLM",
    tagline: "Contracts, delivery & SOW budgets",
    icon: "document",
    land: "/",
  },
  CRM_LITE: {
    label: "CRM Lite",
    tagline: "Leads, campaigns & pipeline",
    icon: "trendingUp",
    land: "/",
  },
};

/** CRM Lite trims out CLM's contract/delivery-only surfaces; CLM in turn
 * doesn't show CRM Lite's admin-only cadence/scoring config pages. Both
 * apps share every other route verbatim (same data, same pages). */
export function isHrefAllowedForApp(pathname: string, app: AppId): boolean {
  if (app === "CRM_LITE") {
    if (pathname.startsWith("/agreements")) return false;
    if (pathname.startsWith("/timesheets")) return false;
    if (pathname.startsWith("/audit")) return false;
    if (pathname.startsWith("/projects")) return false;
    if (pathname.startsWith("/reports")) return false;
    // Users & Teams is shared org-wide (one org, one user directory) —
    // unlike /admin/lookups (CLM-specific agreement/contract config), CRM
    // Lite needs this too so admins can create salespeople and assign roles.
    if (pathname === "/admin/lookups") return false;
    return true;
  }
  if (pathname.startsWith("/admin/cadence-templates") || pathname === "/admin/lead-scoring"
      || pathname === "/admin/products") return false;
  return true;
}
