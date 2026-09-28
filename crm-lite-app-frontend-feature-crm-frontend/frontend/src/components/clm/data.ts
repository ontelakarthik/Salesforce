import type { AppId } from "./apps";
import type { IconName } from "./icons";

export type Role = "SALES" | "ACCOUNT_EXEC" | "LEADERSHIP" | "ADMIN";

export interface RoleInfo {
  avatar: string;
  text: string;
  /** Where this role lands when it can't access the current route. */
  land: string;
}

export const roleInfo: Record<Role, RoleInfo> = {
  SALES: {
    avatar: "AK",
    text: "Sales / Pre-Sales — owns prospects, opportunities and proposals. Read-only on agreements and SOW budgets.",
    land: "/opportunities",
  },
  ACCOUNT_EXEC: {
    avatar: "MR",
    text: "Account Executive — owns projects, SOWs, budgets & timesheet approval. Signs agreements.",
    land: "/",
  },
  LEADERSHIP: {
    avatar: "VN",
    text: "Leadership — read-only visibility across everything, plus org-wide dashboards and alerts.",
    land: "/",
  },
  ADMIN: {
    avatar: "DT",
    text: "Administrator — full access, plus employee, team and lookup management.",
    land: "/",
  },
};

export interface NavItem {
  href: string;
  label: string;
  icon: IconName;
  roles?: Role[];
  /** A real backend capability key (from CAPABILITY_REGISTRY) this item
   * requires — checked against the logged-in employee's actual granted
   * capabilities (state.auth.employee.permissions), not the `roles` field
   * above (which is the UI-only "viewing as" simulator). Lets an admin
   * genuinely hide Leads/Accounts/Opportunities from a profile via Object
   * Permissions, not just simulate it. */
  capability?: string;
}

export interface NavGroup {
  group: string;
  roles?: Role[];
  items: NavItem[];
}

export const navConfig: NavGroup[] = [
  {
    group: "workspace",
    items: [
      { href: "/", label: "Dashboard", icon: "grid" },
      { href: "/radar", label: "Radar", icon: "target", capability: "leads.read" },
      { href: "/campaigns", label: "Campaigns", icon: "star" },
      { href: "/leads", label: "Leads", icon: "userCircle", capability: "leads.read" },
      { href: "/accounts", label: "Accounts", icon: "building", capability: "accounts.read" },
      { href: "/opportunities", label: "Opportunities", icon: "trendingUp", capability: "opportunities.read" },
      { href: "/projects", label: "Projects", icon: "layout" },
      { href: "/reports", label: "Reports", icon: "documentCheck" },
    ],
  },
  {
    group: "agreements",
    items: [
      { href: "/agreements", label: "All agreements", icon: "document" },
    ],
  },
  {
    group: "delivery",
    items: [
      {
        href: "/timesheets",
        label: "Timesheets",
        icon: "clock",
        roles: ["SALES", "ACCOUNT_EXEC", "ADMIN"],
      },
      { href: "/notifications", label: "Notifications", icon: "bell" },
      {
        href: "/audit",
        label: "Audit Log",
        icon: "documentList",
        roles: ["ACCOUNT_EXEC", "LEADERSHIP", "ADMIN"],
      },
    ],
  },
  {
    group: "admin",
    roles: ["ADMIN"],
    items: [
      { href: "/admin/people", label: "Employees & Teams", icon: "users" },
      { href: "/admin/lookups", label: "Lookups", icon: "layers" },
    ],
  },
];

/** CRM Lite's trimmed nav — Campaigns/Leads/Accounts/Opportunities only (no
 * Agreements/Delivery), plus its own admin config for cadence templates and
 * lead scoring rules. Shared hrefs/icons are copy-pasted from navConfig
 * above so the pages they point at render identically in either app. */
export const crmLiteNavConfig: NavGroup[] = [
  {
    group: "workspace",
    items: [
      { href: "/", label: "Dashboard", icon: "grid" },
      { href: "/radar", label: "Radar", icon: "target", capability: "leads.read" },
      { href: "/campaigns", label: "Campaigns", icon: "star" },
      { href: "/leads", label: "Leads", icon: "userCircle", capability: "leads.read" },
      { href: "/accounts", label: "Accounts", icon: "building", capability: "accounts.read" },
      { href: "/opportunities", label: "Opportunities", icon: "trendingUp", capability: "opportunities.read" },
    ],
  },
  {
    group: "admin",
    roles: ["ADMIN"],
    items: [
      { href: "/admin/people", label: "Employees & Teams", icon: "users" },
      { href: "/admin/cadence-templates", label: "Sales Cadences", icon: "layers" },
      { href: "/admin/lead-scoring", label: "Lead Scoring Rules", icon: "documentCheck" },
      { href: "/admin/products", label: "Product Catalog", icon: "documentList" },
      { href: "/admin/territories", label: "Territories", icon: "target" },
      { href: "/admin/field-permissions", label: "Field Permissions", icon: "checkCircle" },
      { href: "/admin/object-permissions", label: "Object Permissions", icon: "grid" },
      { href: "/admin/org-wide-defaults", label: "Org-Wide Defaults", icon: "shield" },
      { href: "/admin/record-shares", label: "Record Sharing", icon: "users" },
      { href: "/admin/profiles", label: "Profiles", icon: "shield" },
    ],
  },
];

export function navConfigForApp(app: AppId): NavGroup[] {
  return app === "CRM_LITE" ? crmLiteNavConfig : navConfig;
}

/** Route-segment → rail group, matching §5's sidebar sections. Order matters (most specific first). */
export function groupForPath(pathname: string): string {
  if (pathname.startsWith("/admin")) return "admin";
  if (pathname.startsWith("/agreements")) return "agreements";
  if (pathname.startsWith("/timesheets") || pathname.startsWith("/notifications") || pathname.startsWith("/audit")) return "delivery";
  return "workspace";
}

const TITLE_RULES: { test: (p: string) => boolean; title: string }[] = [
  { test: (p) => p === "/", title: "Dashboard" },
  { test: (p) => p === "/campaigns", title: "Campaigns" },
  { test: (p) => p === "/leads", title: "Leads" },
  { test: (p) => p === "/accounts", title: "Accounts" },
  { test: (p) => p.startsWith("/accounts/"), title: "Account 360" },
  { test: (p) => p === "/opportunities", title: "Opportunities" },
  { test: (p) => p.startsWith("/opportunities/"), title: "Opportunity 360" },
  { test: (p) => p === "/projects", title: "Projects" },
  { test: (p) => p.startsWith("/projects/"), title: "Project 360" },
  { test: (p) => p === "/reports", title: "Reports" },
  { test: (p) => p === "/agreements", title: "Agreements" },
  { test: (p) => p.startsWith("/agreements/"), title: "Agreement detail" },
  { test: (p) => p === "/timesheets", title: "Timesheets" },
  { test: (p) => p === "/notifications", title: "Notifications" },
  { test: (p) => p === "/audit", title: "Audit Log" },
  { test: (p) => p === "/admin/people", title: "Employees & Teams" },
  { test: (p) => p === "/admin/lookups", title: "Lookups" },
  { test: (p) => p === "/admin/cadence-templates", title: "Sales Cadences" },
  { test: (p) => p.startsWith("/admin/cadence-templates/"), title: "Cadence detail" },
  { test: (p) => p === "/admin/lead-scoring", title: "Lead Scoring Rules" },
  { test: (p) => p === "/admin/products", title: "Product Catalog" },
  { test: (p) => p === "/admin/territories", title: "Territories" },
  { test: (p) => p === "/admin/field-permissions", title: "Field Permissions" },
  { test: (p) => p === "/admin/profiles", title: "Profiles" },
  { test: (p) => p === "/admin/object-permissions", title: "Object Permissions" },
  { test: (p) => p === "/admin/org-wide-defaults", title: "Org-Wide Defaults" },
  { test: (p) => p === "/admin/record-shares", title: "Record Sharing" },
  { test: (p) => p.startsWith("/leads/"), title: "Lead 360" },
];

export function titleForPath(pathname: string): string {
  return TITLE_RULES.find((r) => r.test(pathname))?.title ?? "";
}

/** §3 permission matrix, keyed by route prefix rather than by page id. */
export function isHrefAllowedForRole(pathname: string, role: Role): boolean {
  if (pathname.startsWith("/admin")) return role === "ADMIN";
  if (pathname.startsWith("/timesheets")) return role === "SALES" || role === "ACCOUNT_EXEC" || role === "ADMIN";
  if (pathname.startsWith("/audit")) return role === "ACCOUNT_EXEC" || role === "LEADERSHIP" || role === "ADMIN";
  return true;
}

export function visibleNavItems(
  group: string,
  role: Role,
  app: AppId = "CLM",
  permissions?: string[]
): NavItem[] {
  const g = navConfigForApp(app).find((g) => g.group === group);
  if (!g) return [];
  if (g.roles && !g.roles.includes(role)) return [];
  return g.items.filter((i) => {
    if (i.roles && !i.roles.includes(role)) return false;
    if (i.capability && permissions && !permissions.includes(i.capability)) return false;
    return true;
  });
}

export const groupTitles: Record<string, string> = {
  workspace: "Workspace",
  agreements: "Agreements",
  delivery: "Delivery",
  admin: "Admin",
};

