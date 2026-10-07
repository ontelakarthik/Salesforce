import type { Api } from "./client";

export interface RepActivitySummary {
  owner_employee_id: string | null;
  leads_created: number;
  leads_qualified: number;
  leads_converted: number;
  emails_sent: number;
  calls_made: number;
  // Distinct-lead counts (not activity counts) — a lead with several emails
  // sent still counts once. leads_contacted = >=1 EMAIL/CALL communication;
  // leads_responded = >=1 INBOUND communication (or one marked replied).
  leads_contacted: number;
  leads_responded: number;
}

export interface ManagerDashboardOut {
  date_from: string | null;
  date_to: string | null;
  team_totals: RepActivitySummary;
  per_rep: RepActivitySummary[];
  leaderboard: RepActivitySummary[];
  total_leads: number;
  leads_by_status: Record<string, number>;
  conversion_rate_percent: number | null;
  hot_lead_count: number;
}

/** Leadership/manager team-activity + pipeline view — GET /manager-dashboard.
 * Deliberately not owner-scoped like every other list endpoint (see the
 * backend's manager_dashboard.read capability doc): a manager needs every
 * rep's numbers, not just their own. */
export function getManagerDashboard(api: Api): Promise<ManagerDashboardOut> {
  return api.get<ManagerDashboardOut>("/manager-dashboard");
}

/** One row of the Task Dashboard. owner_employee_id null = "Unassigned"
 * (tasks of leads with no owner). assigned === completed + pending + overdue. */
export interface RepTaskSummary {
  owner_employee_id: string | null;
  assigned: number;
  completed: number;
  pending: number;
  overdue: number;
}

export interface TaskDashboardOut {
  per_rep: RepTaskSummary[];
  team_totals: RepTaskSummary;
}

/** Cadence tasks per assigned rep — GET /task-dashboard. Same
 * manager_dashboard.read gate as getManagerDashboard(), and just as
 * unscoped by "rows I own". */
export function getTaskDashboard(api: Api): Promise<TaskDashboardOut> {
  return api.get<TaskDashboardOut>("/task-dashboard");
}
