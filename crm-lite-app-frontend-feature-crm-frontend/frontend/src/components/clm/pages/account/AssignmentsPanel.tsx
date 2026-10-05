"use client";

import { useEffect, useState, useTransition } from "react";
import RoleOnly from "../../RoleOnly";
import Badge from "../../Badge";
import Modal from "../../Modal";
import Spinner from "../../Spinner";
import { ApiError, useApi } from "@/lib/api/client";
import { useEmployeeDirectory } from "@/lib/api/identity";
import {
  addAssignment,
  listAssignments,
  updateAssignment,
  type AccountAssignmentOut,
} from "@/lib/api/crm";
import { listEmployees, listTeams, type EmployeeOut, type TeamOut } from "@/lib/api/admin";

const ROLE_OPTIONS = [
  { code: "SALES", label: "Sales" },
  { code: "ACCOUNT_EXEC", label: "Account Exec" },
  { code: "LEADERSHIP", label: "Leadership" },
  { code: "ADMIN", label: "Admin" },
];

function roleLabel(code: string): string {
  return ROLE_OPTIONS.find((r) => r.code === code)?.label ?? code;
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export default function AssignmentsPanel({ accountId }: { accountId: string }) {
  const api = useApi();
  const { label } = useEmployeeDirectory();
  const [assignments, setAssignments] = useState<AccountAssignmentOut[] | null>(null);
  const [employees, setEmployees] = useState<EmployeeOut[] | null>(null);
  const [teams, setTeams] = useState<TeamOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [editing, setEditing] = useState<AccountAssignmentOut | null>(null);

  useEffect(() => {
    let cancelled = false;
    listAssignments(api, accountId)
      .then((rows) => {
        if (!cancelled) setAssignments(rows);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Failed to load assignments.");
      });
    // Only Admins can browse the full employee/team directory (admin.ts is
    // gated to the "admin" capability) — silently unavailable for other
    // roles rather than a hard failure, since accounts.assign itself is
    // also open to Account Execs.
    listEmployees(api).then((rows) => !cancelled && setEmployees(rows)).catch(() => !cancelled && setEmployees(null));
    listTeams(api).then((rows) => !cancelled && setTeams(rows)).catch(() => !cancelled && setTeams(null));
    return () => {
      cancelled = true;
    };
  }, [api, accountId]);

  function employeeName(id: string | null): string {
    if (!id) return "—";
    return employees?.find((e) => e.id === id)?.full_name ?? label(id);
  }

  function teamName(id: number | null): string {
    if (id === null) return "—";
    return teams?.find((t) => t.id === id)?.display_name ?? `Team #${id}`;
  }

  function assigneeName(a: AccountAssignmentOut): string {
    return a.employee_id ? employeeName(a.employee_id) : teamName(a.team_id);
  }

  return (
    <div className="card" style={{ marginTop: 20 }}>
      <div className="card-head">
        <h3>Account assignments</h3>
        <div className="spacer" />
        <RoleOnly roles={["ACCOUNT_EXEC", "ADMIN"]}>
          <button className="btn sm" onClick={() => setShowNew(true)}>Add assignment</button>
        </RoleOnly>
      </div>
      {error && <div className="help err" style={{ margin: "12px 16px" }}>{error}</div>}
      {assignments === null && !error ? (
        <div className="card-pad loading-inline"><Spinner /> Loading assignments…</div>
      ) : (
        <table>
          <thead><tr><th>Assignee</th><th>Role</th><th>From</th><th>Until</th><th></th></tr></thead>
          <tbody>
            {(assignments ?? []).map((a) => (
              <tr key={a.id}>
                <td>{assigneeName(a)}</td>
                <td><Badge variant="blue">{roleLabel(a.role)}</Badge></td>
                <td className="t-muted">{formatDate(a.assigned_from)}</td>
                <td className={a.assigned_until ? "t-muted" : "empty-hint"}>{formatDate(a.assigned_until)}</td>
                <td style={{ textAlign: "right" }}>
                  <RoleOnly roles={["ACCOUNT_EXEC", "ADMIN"]}>
                    <button className="btn sm" onClick={() => setEditing(a)}>Edit</button>
                  </RoleOnly>
                </td>
              </tr>
            ))}
            {assignments && assignments.length === 0 && (
              <tr>
                <td colSpan={5} className="empty-hint" style={{ padding: "18px 22px" }}>No one assigned yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      )}
      <NewAssignmentModal
        open={showNew}
        onClose={() => setShowNew(false)}
        accountId={accountId}
        employees={employees}
        teams={teams}
        onCreated={(a) => setAssignments((prev) => (prev ? [a, ...prev] : [a]))}
      />
      <EditAssignmentModal
        assignment={editing}
        onClose={() => setEditing(null)}
        onSaved={(a) => setAssignments((prev) => (prev ?? []).map((x) => (x.id === a.id ? a : x)))}
      />
    </div>
  );
}

function NewAssignmentModal({
  open,
  onClose,
  accountId,
  employees,
  teams,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  accountId: string;
  employees: EmployeeOut[] | null;
  teams: TeamOut[] | null;
  onCreated: (a: AccountAssignmentOut) => void;
}) {
  const api = useApi();
  const [targetType, setTargetType] = useState<"employee" | "team">("employee");
  const [targetId, setTargetId] = useState("");
  const [role, setRole] = useState("");
  const [assignedFrom, setAssignedFrom] = useState("");
  const [assignedUntil, setAssignedUntil] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  function reset() {
    setTargetType("employee");
    setTargetId("");
    setRole("");
    setAssignedFrom("");
    setAssignedUntil("");
    setError(null);
  }

  function close() {
    reset();
    onClose();
  }

  function submit() {
    if (!targetId) {
      setError(`${targetType === "employee" ? "An employee" : "A team"} is required.`);
      return;
    }
    if (!role) {
      setError("Role is required.");
      return;
    }
    if (!assignedFrom) {
      setError("Assigned-from date is required.");
      return;
    }
    startTransition(async () => {
      try {
        const created = await addAssignment(api, accountId, {
          employee_id: targetType === "employee" ? targetId : null,
          team_id: targetType === "team" ? Number(targetId) : null,
          role,
          assigned_from: assignedFrom,
          assigned_until: assignedUntil || null,
        });
        onCreated(created);
        close();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to add assignment.");
      }
    });
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title="Add assignment"
      footer={
        <>
          <button className="btn sm" onClick={close} disabled={isPending}>Cancel</button>
          <div className="spacer" />
          <button className="btn primary sm" onClick={submit} disabled={isPending}>
            {isPending ? "Saving…" : "Save"}
          </button>
        </>
      }
    >
      <div className="fields" style={{ gridTemplateColumns: "repeat(2, 1fr)" }}>
        <div className="field" style={{ gridColumn: "1 / -1" }}>
          <div className="lab">Assign to</div>
          <div style={{ display: "flex", gap: 16 }}>
            <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <input
                type="radio"
                checked={targetType === "employee"}
                onChange={() => {
                  setTargetType("employee");
                  setTargetId("");
                }}
              />
              Employee
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <input
                type="radio"
                checked={targetType === "team"}
                onChange={() => {
                  setTargetType("team");
                  setTargetId("");
                }}
              />
              Team
            </label>
          </div>
        </div>
        {targetType === "employee" ? (
          <div className="field" style={{ gridColumn: "1 / -1" }}>
            <div className="lab">Employee <span className="req">*</span></div>
            {employees === null ? (
              <div className="help err">Employee directory isn&apos;t available for your role — switch to Admin view to assign an employee.</div>
            ) : (
              <select className="inp" value={targetId} onChange={(e) => setTargetId(e.target.value)}>
                <option value="">Select…</option>
                {employees.map((e) => (
                  <option key={e.id} value={e.id}>{e.full_name} ({e.email})</option>
                ))}
              </select>
            )}
          </div>
        ) : (
          <div className="field" style={{ gridColumn: "1 / -1" }}>
            <div className="lab">Team <span className="req">*</span></div>
            {teams === null ? (
              <div className="help err">Team directory isn&apos;t available for your role — switch to Admin view to assign a team.</div>
            ) : (
              <select className="inp" value={targetId} onChange={(e) => setTargetId(e.target.value)}>
                <option value="">Select…</option>
                {teams.map((t) => (
                  <option key={t.id} value={t.id}>{t.display_name}</option>
                ))}
              </select>
            )}
          </div>
        )}
        <div className="field">
          <div className="lab">Role <span className="req">*</span></div>
          <select className="inp" value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="">Select…</option>
            {ROLE_OPTIONS.map((r) => (
              <option key={r.code} value={r.code}>{r.label}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <div className="lab">Assigned from <span className="req">*</span></div>
          <input type="date" className="inp" value={assignedFrom} onChange={(e) => setAssignedFrom(e.target.value)} />
        </div>
        <div className="field">
          <div className="lab">Assigned until</div>
          <input type="date" className="inp" value={assignedUntil} onChange={(e) => setAssignedUntil(e.target.value)} />
        </div>
        {error && <div className="help err" style={{ gridColumn: "1 / -1" }}>{error}</div>}
      </div>
    </Modal>
  );
}

function EditAssignmentModal({
  assignment,
  onClose,
  onSaved,
}: {
  assignment: AccountAssignmentOut | null;
  onClose: () => void;
  onSaved: (a: AccountAssignmentOut) => void;
}) {
  const api = useApi();
  const [role, setRole] = useState("");
  const [assignedUntil, setAssignedUntil] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    if (!assignment) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: fetch/reset state when inputs change
    setRole(assignment.role);
    setAssignedUntil(assignment.assigned_until ?? "");
    setError(null);
  }, [assignment]);

  function submit() {
    if (!assignment) return;
    startTransition(async () => {
      try {
        const updated = await updateAssignment(api, assignment.id, {
          role,
          assigned_until: assignedUntil || null,
        });
        onSaved(updated);
        onClose();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to save assignment.");
      }
    });
  }

  return (
    <Modal
      open={assignment !== null}
      onClose={onClose}
      title="Edit assignment"
      footer={
        <>
          <button className="btn sm" onClick={onClose} disabled={isPending}>Cancel</button>
          <div className="spacer" />
          <button className="btn primary sm" onClick={submit} disabled={isPending}>
            {isPending ? "Saving…" : "Save"}
          </button>
        </>
      }
    >
      <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
        <div className="field">
          <div className="lab">Role <span className="req">*</span></div>
          <select className="inp" value={role} onChange={(e) => setRole(e.target.value)}>
            {ROLE_OPTIONS.map((r) => (
              <option key={r.code} value={r.code}>{r.label}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <div className="lab">Assigned until</div>
          <input type="date" className="inp" value={assignedUntil} onChange={(e) => setAssignedUntil(e.target.value)} />
        </div>
        {error && <div className="help err">{error}</div>}
      </div>
    </Modal>
  );
}
