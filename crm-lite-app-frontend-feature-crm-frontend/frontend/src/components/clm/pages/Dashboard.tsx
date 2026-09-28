"use client";

import { useRouter } from "next/navigation";
import ManagerDashboard from "./ManagerDashboard";
import RepDashboard from "./RepDashboard";
import { logout } from "@/lib/features/authSlice";
import { useAppDispatch, useAppSelector } from "@/lib/hooks";

/** Routes to one of two dashboards based on the logged-in employee's real
 * capabilities (state.auth.employee.permissions — fetched at login, unused
 * anywhere else until now) rather than the "viewing as" UI simulator
 * (RoleOnly/state.role): ManagerDashboard for a profile holding
 * manager_dashboard.read (LEADERSHIP/ADMIN by default, admin-configurable
 * like everything else in Profiles), RepDashboard — "my leads and my
 * work" — for everyone else. */
export default function Dashboard() {
  const router = useRouter();
  const dispatch = useAppDispatch();
  const employee = useAppSelector((state) => state.auth.employee);
  // Roles are baked into the JWT at login time — if an admin grants access
  // after this session started, this tab has no way to know until the user
  // signs out and back in for a fresh token. See the banner below.
  const hasNoRole = employee !== null && employee.roles.length === 0;

  function signOutAndBackIn() {
    dispatch(logout());
    router.replace("/login");
  }

  if (hasNoRole) {
    return (
      <section className="page active">
        <div className="card card-pad" style={{ marginBottom: 20 }}>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>No role assigned yet</div>
          <div className="t-muted" style={{ marginBottom: 14 }}>
            Your account doesn&apos;t have a role yet, so there&apos;s nothing to show here — ask an administrator
            to grant you one in Employees &amp; Teams. If they already have, your current sign-in won&apos;t pick it
            up on its own: sign out and back in to get a session with your new access.
          </div>
          <button className="btn sm" onClick={signOutAndBackIn}>Sign out</button>
        </div>
      </section>
    );
  }

  const sees = employee?.permissions?.includes("manager_dashboard.read") ?? false;
  return sees ? <ManagerDashboard /> : <RepDashboard />;
}
