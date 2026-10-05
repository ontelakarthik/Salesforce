"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import RoleOnly from "../RoleOnly";
import Badge, { type BadgeVariant } from "../Badge";
import Spinner from "../Spinner";
import { ApiError, useApi } from "@/lib/api/client";
import { useEmployeeDirectory } from "@/lib/api/identity";
import { useAppSelector } from "@/lib/hooks";
import { listAgreements, type AgreementOut } from "@/lib/api/contracts";
import {
  approveTimesheet,
  listTeam,
  listTimesheets,
  rejectTimesheet,
  submitTimesheet,
  type SowTeamMemberOut,
  type SowTimesheetOut,
} from "@/lib/api/delivery";

const STATUS_BADGE: Record<string, BadgeVariant> = {
  SUBMITTED: "amber",
  APPROVED: "green",
  REJECTED: "red",
};

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

function memberLabel(employeeLabel: (id: string | null) => string, member: SowTeamMemberOut | undefined): string {
  if (!member) return "—";
  return member.external_name ?? employeeLabel(member.employee_id);
}

export default function Timesheet() {
  const api = useApi();
  const { label: employeeLabel } = useEmployeeDirectory();
  const currentEmployeeId = useAppSelector((state) => state.auth.employee?.employee_id) ?? null;
  const [timesheets, setTimesheets] = useState<SowTimesheetOut[] | null>(null);
  const [sowAgreements, setSowAgreements] = useState<AgreementOut[]>([]);
  const [teamByAgreement, setTeamByAgreement] = useState<Record<string, SowTeamMemberOut[]>>({});
  const [error, setError] = useState<string | null>(null);

  const [formAgreementId, setFormAgreementId] = useState("");
  const [formMemberId, setFormMemberId] = useState("");
  const [weekStart, setWeekStart] = useState("");
  const [hours, setHours] = useState("");
  const [notes, setNotes] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [isSubmitting, startSubmit] = useTransition();
  const [busyId, setBusyId] = useState<string | null>(null);

  async function ensureTeamLoaded(agreementId: string) {
    if (!agreementId || teamByAgreement[agreementId]) return;
    try {
      const members = await listTeam(api, agreementId);
      setTeamByAgreement((prev) => ({ ...prev, [agreementId]: members }));
    } catch {
      setTeamByAgreement((prev) => ({ ...prev, [agreementId]: [] }));
    }
  }

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: fetch/reset state when inputs change
    setTimesheets(null);
    setError(null);
    Promise.all([listTimesheets(api), listAgreements(api)])
      .then(async ([rows, agreements]) => {
        if (cancelled) return;
        setTimesheets(rows);
        setSowAgreements(agreements.filter((a) => a.agreement_type === "SOW"));
        const distinctAgreementIds = [...new Set(rows.map((r) => r.agreement_id))];
        await Promise.all(distinctAgreementIds.map((aid) => ensureTeamLoaded(aid)));
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Failed to load timesheets.");
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);

  const formTeamMembers = teamByAgreement[formAgreementId] ?? [];

  function findMember(agreementId: string, memberId: string): SowTeamMemberOut | undefined {
    return teamByAgreement[agreementId]?.find((m) => m.id === memberId);
  }

  function resetForm() {
    setFormMemberId("");
    setWeekStart("");
    setHours("");
    setNotes("");
    setFormError(null);
  }

  function submit() {
    if (!formAgreementId || !formMemberId) {
      setFormError("SOW and team member are required.");
      return;
    }
    if (!weekStart) {
      setFormError("Week starting date is required.");
      return;
    }
    if (new Date(weekStart + "T00:00:00").getDay() !== 1) {
      setFormError("Week starting date must be a Monday.");
      return;
    }
    const hoursNum = Number(hours);
    if (!hours.trim() || Number.isNaN(hoursNum) || hoursNum <= 0 || hoursNum > 168) {
      setFormError("Hours must be greater than 0 and at most 168.");
      return;
    }
    startSubmit(async () => {
      try {
        const created = await submitTimesheet(api, {
          sow_team_member_id: formMemberId,
          agreement_id: formAgreementId,
          week_start_date: weekStart,
          hours: hoursNum,
          notes: notes.trim() || null,
        });
        setTimesheets((prev) => (prev ? [created, ...prev] : [created]));
        resetForm();
      } catch (err) {
        setFormError(err instanceof ApiError ? err.message : "Failed to submit timesheet.");
      }
    });
  }

  function decide(timesheetId: string, action: "approve" | "reject") {
    setBusyId(timesheetId);
    setError(null);
    (action === "approve" ? approveTimesheet(api, timesheetId) : rejectTimesheet(api, timesheetId))
      .then((updated) => {
        setTimesheets((prev) => (prev ?? []).map((t) => (t.id === updated.id ? updated : t)));
      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Failed to update timesheet.");
      })
      .finally(() => setBusyId(null));
  }

  const pending = (timesheets ?? []).filter((t) => t.status === "SUBMITTED");

  const sorted = useMemo(
    () => [...(timesheets ?? [])].sort((a, b) => b.week_start_date.localeCompare(a.week_start_date)),
    [timesheets]
  );

  return (
    <section className="page active">
      <div className="pagehead">
        <div>
          <h1>Timesheets</h1>
          <div className="sub">Weekly hours across all your SOWs</div>
        </div>
      </div>
      {error && <div className="help err" style={{ margin: "12px 0" }}>{error}</div>}
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
          <div className="card">
            <div className="card-head">
              <h3>Submit hours</h3>
              <div className="spacer" />
              <Badge variant="gray">Week starts Monday</Badge>
            </div>
            <div className="card-pad">
              <div className="fields" style={{ gridTemplateColumns: "1fr 1fr" }}>
                <div className="field">
                  <div className="lab">SOW <span className="req">*</span></div>
                  <select
                    className="inp"
                    value={formAgreementId}
                    onChange={(e) => {
                      setFormAgreementId(e.target.value);
                      setFormMemberId("");
                      ensureTeamLoaded(e.target.value);
                    }}
                  >
                    <option value="">Select…</option>
                    {sowAgreements.map((a) => (
                      <option key={a.id} value={a.id}>{a.id} · {a.title}</option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <div className="lab">Team member <span className="req">*</span></div>
                  <select
                    className="inp"
                    value={formMemberId}
                    onChange={(e) => setFormMemberId(e.target.value)}
                    disabled={!formAgreementId}
                  >
                    <option value="">Select…</option>
                    {formTeamMembers.map((m) => (
                      <option key={m.id} value={m.id}>{memberLabel(employeeLabel, m)}</option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <div className="lab">Week starting <span className="req">*</span></div>
                  <input type="date" className="inp" value={weekStart} onChange={(e) => setWeekStart(e.target.value)} />
                  <div className="help">Must be a Monday.</div>
                </div>
                <div className="field">
                  <div className="lab">Hours <span className="req">*</span></div>
                  <input className="inp" type="number" value={hours} onChange={(e) => setHours(e.target.value)} />
                  <div className="help">0–168; greater than 0 to submit.</div>
                </div>
                <div className="field" style={{ gridColumn: "1 / -1" }}>
                  <div className="lab">Notes</div>
                  <input className="inp" value={notes} onChange={(e) => setNotes(e.target.value)} />
                </div>
              </div>
              <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
                <button className="btn primary sm" onClick={submit} disabled={isSubmitting}>
                  {isSubmitting ? "Submitting…" : "Submit for approval"}
                </button>
              </div>
              {formError && <div className="help err" style={{ marginTop: 10 }}>{formError}</div>}
              <div className="help" style={{ marginTop: 12 }}>
                One entry per member per week. You can&apos;t approve your own submission.
              </div>
            </div>
          </div>
        </RoleOnly>
        <RoleOnly roles={["ACCOUNT_EXEC", "ADMIN"]}>
          <div className="card">
            <div className="card-head">
              <h3>Pending approval</h3>
              <div className="spacer" />
              <Badge variant="amber">{pending.length}</Badge>
            </div>
            <table>
              <thead><tr><th>Member</th><th>Week</th><th>Hrs</th><th></th></tr></thead>
              <tbody>
                {pending.map((t) => {
                  const member = findMember(t.agreement_id, t.sow_team_member_id);
                  const isOwn = t.submitted_by_employee_id === currentEmployeeId;
                  return (
                    <tr key={t.id}>
                      <td style={{ whiteSpace: "nowrap" }}>{memberLabel(employeeLabel, member)}</td>
                      <td className="t-muted" style={{ whiteSpace: "nowrap" }}>{formatDate(t.week_start_date)}</td>
                      <td className="num">{t.hours}</td>
                      <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                        {isOwn ? (
                          <span className="empty-hint">Your own — can&apos;t approve</span>
                        ) : (
                          <>
                            <button
                              className="btn sm"
                              style={{ marginRight: 6 }}
                              disabled={busyId === t.id}
                              onClick={() => decide(t.id, "approve")}
                            >
                              Approve
                            </button>
                            <button className="btn sm" disabled={busyId === t.id} onClick={() => decide(t.id, "reject")}>
                              Reject
                            </button>
                          </>
                        )}
                      </td>
                    </tr>
                  );
                })}
                {pending.length === 0 && (
                  <tr>
                    <td colSpan={4} className="empty-hint" style={{ padding: "18px 22px" }}>Nothing pending.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </RoleOnly>
      </div>
      <div className="section-title">
        All entries <span className="line" />
      </div>
      <div className="card">
        {timesheets === null && !error ? (
          <div className="card-pad loading-inline"><Spinner /> Loading timesheets…</div>
        ) : (
          <table>
            <thead><tr><th>Member</th><th>SOW</th><th>Week</th><th>Hours</th><th>Status</th></tr></thead>
            <tbody>
              {sorted.map((t) => {
                const member = findMember(t.agreement_id, t.sow_team_member_id);
                return (
                  <tr key={t.id}>
                    <td style={{ whiteSpace: "nowrap" }}>{memberLabel(employeeLabel, member)}</td>
                    <td className="mono t-muted">{t.agreement_id}</td>
                    <td className="t-muted">{formatDate(t.week_start_date)}</td>
                    <td className="num">{t.hours}</td>
                    <td><Badge variant={STATUS_BADGE[t.status] ?? "gray"}>{t.status.charAt(0) + t.status.slice(1).toLowerCase()}</Badge></td>
                  </tr>
                );
              })}
              {sorted.length === 0 && (
                <tr>
                  <td colSpan={5} className="empty-hint" style={{ padding: "18px 22px" }}>No timesheets yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
