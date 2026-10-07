"use client";

import { useEffect, useState } from "react";
import Spinner from "../Spinner";
import { fetchGraceful, useApi } from "@/lib/api/client";
import { useEmployeeDirectory } from "@/lib/api/identity";
import { getTaskDashboard, type TaskDashboardOut } from "@/lib/api/platform";

/** Cadence tasks per rep — Assigned / Completed / Pending / Overdue. A
 * separate card (and endpoint) from the Rep leaderboard: tasks only, no lead
 * metrics. Pending includes skipped tasks that aren't yet past due; Overdue
 * is any not-completed task past its due date. See the backend's
 * platform_service.task_dashboard(). */
export default function TaskDashboard() {
  const api = useApi();
  const { label: employeeLabel } = useEmployeeDirectory();
  const [data, setData] = useState<TaskDashboardOut | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: fetch/reset state when inputs change
    setError(null);
    fetchGraceful(getTaskDashboard(api)).then((res) => {
      if (cancelled) return;
      setData(res.ok ? res.value : null);
      setForbidden(!res.ok && res.forbidden);
      setError(!res.ok && !res.forbidden ? res.message : null);
    });
    return () => {
      cancelled = true;
    };
  }, [api]);

  if (forbidden) return null;

  if (error) {
    return <div className="card card-pad help err" style={{ marginBottom: 20 }}>{error}</div>;
  }

  if (!data) {
    return <div className="card card-pad loading-inline" style={{ marginBottom: 20 }}><Spinner /> Loading task dashboard…</div>;
  }

  return (
    <div className="card" style={{ marginBottom: 20 }}>
      <div className="card-head"><h3>Task Dashboard</h3></div>
      <table>
        <thead><tr><th>Rep</th><th>Assigned</th><th>Completed</th><th>Pending</th><th>Overdue</th></tr></thead>
        <tbody>
          {data.per_rep.map((r) => (
            <tr key={r.owner_employee_id ?? "unassigned"}>
              <td style={{ whiteSpace: "nowrap" }}>{r.owner_employee_id ? employeeLabel(r.owner_employee_id) : "Unassigned"}</td>
              <td className="num">{r.assigned}</td>
              <td className="num">{r.completed}</td>
              <td className="num">{r.pending}</td>
              <td className="num">{r.overdue}</td>
            </tr>
          ))}
          {data.per_rep.length === 0 && (
            <tr><td colSpan={5} className="empty-hint" style={{ padding: "18px 22px" }}>No tasks yet.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
