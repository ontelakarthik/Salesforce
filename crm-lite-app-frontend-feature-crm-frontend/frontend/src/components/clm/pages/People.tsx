"use client";

import { useEffect, useState, useTransition } from "react";
import Badge, { type BadgeVariant } from "../Badge";
import Modal from "../Modal";
import RoleOnly from "../RoleOnly";
import Tabs from "../Tabs";
import Spinner from "../Spinner";
import { Icon } from "../icons";
import { ApiError, useApi } from "@/lib/api/client";
import {
  createEmployee,
  createTeam,
  listEmployees,
  listLookups,
  listTeams,
  setEmployeeProfiles,
  updateEmployee,
  updateTeam,
  type EmployeeCreateOut,
  type EmployeeOut,
  type LookupOut,
  type TeamOut,
} from "@/lib/api/admin";
import { listProfiles, type ProfileOut } from "@/lib/api/profiles";

const ROLE_BADGE: Record<string, BadgeVariant> = {
  SALES: "teal",
  ACCOUNT_EXEC: "blue",
  LEADERSHIP: "violet",
  ADMIN: "gray",
};

const AVATAR_COLORS = ["#2F5FA6", "#6D45B8", "#0E8A7D", "#B45309", "#64748B", "#2F5FA6", "#6D45B8", "#0E8A7D"];

function initialsFor(name: string): string {
  return name.split(" ").map((p) => p[0]).join("").slice(0, 2).toUpperCase();
}

export default function People() {
  return (
    <section className="page active">
      <div className="pagehead">
        <div>
          <h1>Employees &amp; Teams</h1>
          <div className="sub">Manage internal users, profiles, and distribution lists</div>
        </div>
      </div>
      <Tabs
        tabs={[
          { id: "p-emp", label: "Employees", content: <Employees /> },
          { id: "p-team", label: "Teams", content: <Teams /> },
        ]}
      />
    </section>
  );
}

function Employees() {
  const api = useApi();
  const [employees, setEmployees] = useState<EmployeeOut[] | null>(null);
  const [roles, setRoles] = useState<ProfileOut[]>([]);
  const [territories, setTerritories] = useState<LookupOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [editing, setEditing] = useState<EmployeeOut | null>(null);

  useEffect(() => {
    let cancelled = false;
    setEmployees(null);
    setError(null);
    Promise.all([listEmployees(api), listProfiles(api), listLookups(api, "territory")])
      .then(([emps, roleRows, territoryRows]) => {
        if (cancelled) return;
        setEmployees(emps);
        setRoles(roleRows);
        // Kept unfiltered here — each dropdown below filters to Active
        // itself, but an edit form also needs the currently-assigned
        // territory even if it's since gone inactive (see EditEmployeeModal).
        setTerritories(territoryRows);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Failed to load employees.");
      });
    return () => {
      cancelled = true;
    };
  }, [api]);

  return (
    <div className="card">
      <div className="card-head">
        <h3>Employees</h3>
        <div className="spacer" />
        <RoleOnly roles={["ADMIN"]}>
          <button className="btn sm" onClick={() => setShowNew(true)}>
            <Icon name="plus" />
            Add employee
          </button>
        </RoleOnly>
      </div>
      {error && <div className="help err" style={{ margin: "12px 16px" }}>{error}</div>}
      {employees === null && !error ? (
        <div className="card-pad loading-inline"><Spinner /> Loading employees…</div>
      ) : (
        <table>
          <thead><tr><th>Name</th><th>Email</th><th>Profiles</th><th>Territory</th><th>Status</th><th></th></tr></thead>
          <tbody>
            {(employees ?? []).map((e, i) => (
              <tr key={e.id}>
                <td className="person">
                  <span className="avatar-sm" style={{ background: AVATAR_COLORS[i % AVATAR_COLORS.length] }}>{initialsFor(e.full_name)}</span>
                  {e.full_name}
                </td>
                <td>{e.email}</td>
                <td>
                  {e.roles.length > 0
                    ? e.roles.map((code) => (
                        <Badge key={code} variant={ROLE_BADGE[code] ?? "gray"} style={{ marginRight: 4 }}>
                          {roles.find((r) => r.code === code)?.display_name ?? code}
                        </Badge>
                      ))
                    : <span className="empty-hint">— none</span>}
                </td>
                <td>{e.territory_name ?? <span className="empty-hint">—</span>}</td>
                <td>
                  {e.is_active ? <Badge variant="green">Active</Badge> : <Badge variant="gray">Inactive</Badge>}
                  {e.is_active && e.must_change_password && (
                    <Badge variant="amber" style={{ marginLeft: 4 }}>Never logged in</Badge>
                  )}
                </td>
                <td style={{ textAlign: "right" }}>
                  <RoleOnly roles={["ADMIN"]}>
                    <button className="btn sm" onClick={() => setEditing(e)}>Edit</button>
                  </RoleOnly>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <NewEmployeeModal
        open={showNew}
        roles={roles}
        territories={territories}
        onClose={() => setShowNew(false)}
        onCreated={(created) => setEmployees((prev) => (prev ? [created, ...prev] : [created]))}
      />
      <EditEmployeeModal
        employee={editing}
        roles={roles}
        territories={territories}
        onClose={() => setEditing(null)}
        onSaved={(updated) => setEmployees((prev) => (prev ?? []).map((x) => (x.id === updated.id ? updated : x)))}
      />
    </div>
  );
}

function NewEmployeeModal({
  open,
  roles,
  territories,
  onClose,
  onCreated,
}: {
  open: boolean;
  roles: ProfileOut[];
  territories: LookupOut[];
  onClose: () => void;
  onCreated: (employee: EmployeeOut) => void;
}) {
  const api = useApi();
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [roleCodes, setRoleCodes] = useState<string[]>([]);
  const [territoryId, setTerritoryId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  // Set once creation succeeds — the modal then shows a confirmation (with
  // whether the welcome email actually sent) instead of just closing, same
  // as Salesforce's "New User" flow does.
  const [created, setCreated] = useState<EmployeeCreateOut | null>(null);
  // True if the employee row was created but the follow-up role-assignment
  // call failed — the employee still exists (not undone), so this surfaces
  // as a warning on the confirmation screen rather than a submit error.
  const [rolesFailed, setRolesFailed] = useState(false);

  function toggleRole(code: string) {
    setRoleCodes((prev) => (prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code]));
  }

  function reset() {
    setEmail("");
    setFullName("");
    setRoleCodes([]);
    setTerritoryId("");
    setError(null);
    setCreated(null);
    setRolesFailed(false);
  }

  function close() {
    if (created) onCreated(created);
    reset();
    onClose();
  }

  function submit() {
    if (!email.trim() || !fullName.trim()) {
      setError("Email and full name are required.");
      return;
    }
    if (roleCodes.length === 0) {
      setError("Select at least one profile — this decides what they can do.");
      return;
    }
    startTransition(async () => {
      let createdEmp: EmployeeCreateOut;
      try {
        createdEmp = await createEmployee(api, {
          email: email.trim(), full_name: fullName.trim(),
          territory_id: territoryId ? Number(territoryId) : null,
        });
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to add employee.");
        return;
      }
      try {
        const withRoles = await setEmployeeProfiles(api, createdEmp.id, roleCodes);
        setCreated({ ...withRoles, password_email_sent: createdEmp.password_email_sent });
      } catch {
        setCreated(createdEmp);
        setRolesFailed(true);
      }
    });
  }

  if (created) {
    return (
      <Modal
        open={open}
        onClose={close}
        title="Employee added"
        footer={<button className="btn primary sm" onClick={close} style={{ marginLeft: "auto" }}>Done</button>}
      >
        <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
          <div className="help" style={{ color: created.password_email_sent ? "var(--green)" : "var(--amber)" }}>
            {created.password_email_sent
              ? `A welcome email with a temporary password was sent to ${created.email}.`
              : `${created.full_name} was created, but the welcome email couldn't be sent (email isn't configured, or delivery failed) — share their login details with them another way.`}
          </div>
          <div className="help" style={{ color: rolesFailed ? "var(--amber)" : undefined }}>
            {rolesFailed
              ? "Profile assignment failed — use “Edit” on their row to grant one before they can sign in."
              : `Assigned as ${created.roles.map((code) => roles.find((r) => r.code === code)?.display_name ?? code).join(", ")}.`}
          </div>
        </div>
      </Modal>
    );
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title="Add employee"
      footer={
        <>
          <button className="btn sm" onClick={close} disabled={isPending}>Cancel</button>
          <div className="spacer" />
          <button className="btn primary sm" onClick={submit} disabled={isPending}>{isPending ? "Saving…" : "Save"}</button>
        </>
      }
    >
      <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
        <div className="field">
          <div className="lab">Full name <span className="req">*</span></div>
          <input className="inp" value={fullName} onChange={(e) => setFullName(e.target.value)} autoFocus />
        </div>
        <div className="field">
          <div className="lab">Email <span className="req">*</span></div>
          <input className="inp" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="field">
          <div className="lab">Profile <span className="req">*</span></div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
            {roles.map((r) => (
              <label key={r.code} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <input type="checkbox" checked={roleCodes.includes(r.code)} onChange={() => toggleRole(r.code)} />
                {r.display_name}
              </label>
            ))}
          </div>
        </div>
        <div className="field">
          <div className="lab">Territory / Region</div>
          <select className="inp" value={territoryId} onChange={(e) => setTerritoryId(e.target.value)}>
            <option value="">— none —</option>
            {territories.filter((t) => t.is_active !== false).map((t) => (
              <option key={t.id} value={t.id}>{t.display_name}</option>
            ))}
          </select>
          <div className="help">
            Used to default the territory of Accounts/Leads this employee creates — see Admin → Territories.
          </div>
        </div>
        <div className="help">
          A temporary password is generated automatically and emailed to them — they&apos;ll set their own on first
          sign-in, and can sign in as soon as they have a role.
        </div>
        {error && <div className="help err">{error}</div>}
      </div>
    </Modal>
  );
}

function EditEmployeeModal({
  employee,
  roles,
  territories,
  onClose,
  onSaved,
}: {
  employee: EmployeeOut | null;
  roles: ProfileOut[];
  territories: LookupOut[];
  onClose: () => void;
  onSaved: (employee: EmployeeOut) => void;
}) {
  const api = useApi();
  const [fullName, setFullName] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [roleCodes, setRoleCodes] = useState<string[]>([]);
  const [territoryId, setTerritoryId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    if (!employee) return;
    setFullName(employee.full_name);
    setIsActive(employee.is_active);
    setRoleCodes(employee.roles);
    setTerritoryId(employee.territory_id != null ? String(employee.territory_id) : "");
    setError(null);
  }, [employee]);

  function toggleRole(code: string) {
    setRoleCodes((prev) => (prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code]));
  }

  function submit() {
    if (!employee) return;
    if (!fullName.trim()) {
      setError("Full name is required.");
      return;
    }
    startTransition(async () => {
      try {
        await updateEmployee(api, employee.id, {
          full_name: fullName.trim(), is_active: isActive,
          territory_id: territoryId ? Number(territoryId) : null,
        });
        const withRoles = await setEmployeeProfiles(api, employee.id, roleCodes);
        onSaved(withRoles);
        onClose();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to save employee.");
      }
    });
  }

  return (
    <Modal
      open={employee !== null}
      onClose={onClose}
      title={employee ? `Edit ${employee.full_name}` : "Edit employee"}
      footer={
        <>
          <button className="btn sm" onClick={onClose} disabled={isPending}>Cancel</button>
          <div className="spacer" />
          <button className="btn primary sm" onClick={submit} disabled={isPending}>{isPending ? "Saving…" : "Save"}</button>
        </>
      }
    >
      <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
        <div className="field">
          <div className="lab">Full name <span className="req">*</span></div>
          <input className="inp" value={fullName} onChange={(e) => setFullName(e.target.value)} autoFocus />
        </div>
        <div className="field">
          <div className="lab">Email</div>
          <div className="val t-muted">{employee?.email}</div>
        </div>
        <div className="field">
          <label className="val" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
            Active
          </label>
        </div>
        <div className="field">
          <div className="lab">Territory / Region</div>
          <select className="inp" value={territoryId} onChange={(e) => setTerritoryId(e.target.value)}>
            <option value="">— none —</option>
            {territories.filter((t) => t.is_active !== false).map((t) => (
              <option key={t.id} value={t.id}>{t.display_name}</option>
            ))}
            {/* The employee's already-assigned territory may have since
                gone inactive — still show it (disabled from re-selection
                logic aside, only new/changed assignments must be Active),
                so an existing assignment never silently looks unset. */}
            {employee?.territory_id != null
              && !territories.some((t) => t.id === employee.territory_id && t.is_active !== false)
              && (() => {
                const current = territories.find((t) => t.id === employee.territory_id);
                return current ? (
                  <option key={current.id} value={current.id}>{current.display_name} (Inactive)</option>
                ) : null;
              })()}
          </select>
        </div>
        <div className="field">
          <div className="lab">Profiles</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
            {roles.map((r) => (
              <label key={r.code} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <input type="checkbox" checked={roleCodes.includes(r.code)} onChange={() => toggleRole(r.code)} />
                {r.display_name}
              </label>
            ))}
          </div>
        </div>
        {error && <div className="help err">{error}</div>}
      </div>
    </Modal>
  );
}

function Teams() {
  const api = useApi();
  const [teams, setTeams] = useState<TeamOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [editing, setEditing] = useState<TeamOut | null>(null);

  useEffect(() => {
    let cancelled = false;
    setTeams(null);
    setError(null);
    listTeams(api)
      .then((rows) => {
        if (!cancelled) setTeams(rows);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Failed to load teams.");
      });
    return () => {
      cancelled = true;
    };
  }, [api]);

  return (
    <div className="card">
      <div className="card-head">
        <h3>Teams (distribution lists)</h3>
        <div className="spacer" />
        <RoleOnly roles={["ADMIN"]}>
          <button className="btn sm" onClick={() => setShowNew(true)}>
            <Icon name="plus" />
            Add team
          </button>
        </RoleOnly>
      </div>
      {error && <div className="help err" style={{ margin: "12px 16px" }}>{error}</div>}
      {teams === null && !error ? (
        <div className="card-pad loading-inline"><Spinner /> Loading teams…</div>
      ) : (
        <table>
          <thead><tr><th>Display name</th><th>Address</th><th>Purpose</th><th>Active</th><th></th></tr></thead>
          <tbody>
            {(teams ?? []).map((t) => (
              <tr key={t.id}>
                <td className="t-strong">{t.display_name}</td>
                <td>{t.address ?? "—"}</td>
                <td>{t.purpose ?? "—"}</td>
                <td>{t.is_active ? <Badge variant="green">Active</Badge> : <Badge variant="gray">Inactive</Badge>}</td>
                <td style={{ textAlign: "right" }}>
                  <RoleOnly roles={["ADMIN"]}>
                    <button className="btn sm" onClick={() => setEditing(t)}>Edit</button>
                  </RoleOnly>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="card-pad" style={{ borderTop: "1px solid var(--border)" }}>
        <div className="help">Membership is managed in Microsoft 365, not here — this manages the DL address, purpose and status only.</div>
      </div>
      <NewTeamModal
        open={showNew}
        onClose={() => setShowNew(false)}
        onCreated={(created) => setTeams((prev) => (prev ? [created, ...prev] : [created]))}
      />
      <EditTeamModal
        team={editing}
        onClose={() => setEditing(null)}
        onSaved={(updated) => setTeams((prev) => (prev ?? []).map((x) => (x.id === updated.id ? updated : x)))}
      />
    </div>
  );
}

function NewTeamModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (team: TeamOut) => void;
}) {
  const api = useApi();
  const [displayName, setDisplayName] = useState("");
  const [purpose, setPurpose] = useState("");
  const [address, setAddress] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  function reset() {
    setDisplayName("");
    setPurpose("");
    setAddress("");
    setError(null);
  }

  function close() {
    reset();
    onClose();
  }

  function submit() {
    if (!displayName.trim()) {
      setError("Display name is required.");
      return;
    }
    startTransition(async () => {
      try {
        const created = await createTeam(api, {
          display_name: displayName.trim(),
          purpose: purpose.trim() || null,
          address: address.trim() || null,
        });
        onCreated(created);
        close();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to add team.");
      }
    });
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title="Add team"
      footer={
        <>
          <button className="btn sm" onClick={close} disabled={isPending}>Cancel</button>
          <div className="spacer" />
          <button className="btn primary sm" onClick={submit} disabled={isPending}>{isPending ? "Saving…" : "Save"}</button>
        </>
      }
    >
      <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
        <div className="field">
          <div className="lab">Display name <span className="req">*</span></div>
          <input className="inp" value={displayName} onChange={(e) => setDisplayName(e.target.value)} autoFocus />
        </div>
        <div className="field">
          <div className="lab">Address</div>
          <input className="inp" value={address} onChange={(e) => setAddress(e.target.value)} placeholder="team-dl@tachyon.com" />
        </div>
        <div className="field">
          <div className="lab">Purpose</div>
          <input className="inp" value={purpose} onChange={(e) => setPurpose(e.target.value)} />
        </div>
        {error && <div className="help err">{error}</div>}
      </div>
    </Modal>
  );
}

function EditTeamModal({
  team,
  onClose,
  onSaved,
}: {
  team: TeamOut | null;
  onClose: () => void;
  onSaved: (team: TeamOut) => void;
}) {
  const api = useApi();
  const [displayName, setDisplayName] = useState("");
  const [purpose, setPurpose] = useState("");
  const [address, setAddress] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    if (!team) return;
    setDisplayName(team.display_name);
    setPurpose(team.purpose ?? "");
    setAddress(team.address ?? "");
    setIsActive(team.is_active);
    setError(null);
  }, [team]);

  function submit() {
    if (!team) return;
    if (!displayName.trim()) {
      setError("Display name is required.");
      return;
    }
    startTransition(async () => {
      try {
        const updated = await updateTeam(api, team.id, {
          display_name: displayName.trim(),
          purpose: purpose.trim() || null,
          address: address.trim() || null,
          is_active: isActive,
        });
        onSaved(updated);
        onClose();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to save team.");
      }
    });
  }

  return (
    <Modal
      open={team !== null}
      onClose={onClose}
      title={team ? `Edit ${team.display_name}` : "Edit team"}
      footer={
        <>
          <button className="btn sm" onClick={onClose} disabled={isPending}>Cancel</button>
          <div className="spacer" />
          <button className="btn primary sm" onClick={submit} disabled={isPending}>{isPending ? "Saving…" : "Save"}</button>
        </>
      }
    >
      <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
        <div className="field">
          <div className="lab">Display name <span className="req">*</span></div>
          <input className="inp" value={displayName} onChange={(e) => setDisplayName(e.target.value)} autoFocus />
        </div>
        <div className="field">
          <div className="lab">Address</div>
          <input className="inp" value={address} onChange={(e) => setAddress(e.target.value)} />
        </div>
        <div className="field">
          <div className="lab">Purpose</div>
          <input className="inp" value={purpose} onChange={(e) => setPurpose(e.target.value)} />
        </div>
        <div className="field">
          <label className="val" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
            Active
          </label>
        </div>
        {error && <div className="help err">{error}</div>}
      </div>
    </Modal>
  );
}
