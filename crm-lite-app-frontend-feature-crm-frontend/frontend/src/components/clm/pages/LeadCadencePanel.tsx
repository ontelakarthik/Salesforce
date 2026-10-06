"use client";

import { useEffect, useState, useTransition } from "react";
import RoleOnly from "../RoleOnly";
import Badge, { type BadgeVariant } from "../Badge";
import { ApiError, useApi } from "@/lib/api/client";
import {
  cancelLeadCadence,
  completeCadenceTask,
  getCadenceTemplate,
  getLeadCadence,
  reopenCadenceTask,
  skipCadenceTask,
  type CadenceTaskOut,
  type CadenceTemplateOut,
  type LeadCadenceDetailOut,
} from "@/lib/api/cadence";
import EnrollCadenceModal from "./EnrollCadenceModal";

const STEP_TYPE_BADGE: Record<string, BadgeVariant> = {
  CALL: "teal",
  EMAIL: "blue",
  LINKEDIN: "violet",
  BREAK: "amber",
  FOLLOW_UP: "green",
  OTHER: "gray",
};

function formatDate(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

/** "Today"/"Tomorrow"/"Day N" framing for an upcoming task's due date, so
 * the cadence's next actions read the way the business described them
 * (e.g. "Today: Call Lead", "Tomorrow: Send Email") rather than only as a
 * bare calendar date. */
function relativeDueLabel(value: string | null): string | null {
  if (!value) return null;
  const due = new Date(value);
  if (Number.isNaN(due.getTime())) return null;
  const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diffDays = Math.round((startOfDay(due).getTime() - startOfDay(new Date()).getTime()) / 86400000);
  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Tomorrow";
  if (diffDays === -1) return "Yesterday";
  if (diffDays > 1) return `Day ${diffDays}`;
  return null;
}

export default function LeadCadencePanel({ leadId }: { leadId: string }) {
  const api = useApi();
  const [detail, setDetail] = useState<LeadCadenceDetailOut | null | undefined>(undefined);
  const [template, setTemplate] = useState<CadenceTemplateOut | null>(null);
  const [showEnroll, setShowEnroll] = useState(false);
  // Notes are per task: a reopened task can sit beside the next step's task, both actionable.
  const [notesByTask, setNotesByTask] = useState<Record<string, string>>({});
  const [actionError, setActionError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const [isCancelling, setIsCancelling] = useState(false);

  function load() {
    getLeadCadence(api, leadId)
      .then((d) => {
        setDetail(d);
        setNotesByTask({});
        if (d) {
          getCadenceTemplate(api, d.enrollment.cadence_template_id)
            .then(setTemplate)
            .catch(() => setTemplate(null));
        } else {
          setTemplate(null);
        }
      })
      .catch(() => setDetail(null));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, leadId]);

  function cancelEnrollment() {
    if (!window.confirm("Cancel this cadence? The remaining step won't be sent, and this can't be undone.")) return;
    setActionError(null);
    setIsCancelling(true);
    cancelLeadCadence(api, leadId)
      .then(() => load())
      .catch((err: unknown) => {
        setActionError(err instanceof ApiError ? err.message : "Failed to cancel cadence.");
      })
      .finally(() => setIsCancelling(false));
  }

  function respondToTask(taskId: string, outcome: "DONE" | "SKIPPED") {
    setActionError(null);
    startTransition(async () => {
      try {
        const notes = (notesByTask[taskId] ?? "").trim() || undefined;
        if (outcome === "DONE") await completeCadenceTask(api, taskId, notes);
        else await skipCadenceTask(api, taskId, notes);
        load();
      } catch (err) {
        setActionError(err instanceof ApiError ? err.message : "Failed to update task.");
      }
    });
  }

  function reopenTask(taskId: string) {
    setActionError(null);
    startTransition(async () => {
      try {
        await reopenCadenceTask(api, taskId);
        load();
      } catch (err) {
        setActionError(err instanceof ApiError ? err.message : "Failed to reopen task.");
      }
    });
  }

  const tasks: CadenceTaskOut[] = detail ? [...detail.tasks].sort((a, b) => a.due_date.localeCompare(b.due_date)) : [];

  return (
    <div className="card">
      <div className="card-head">
        <h3>Sales cadence</h3>
        <div className="spacer" />
        {detail && detail.enrollment.status === "ACTIVE" && (
          <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
            <button className="btn sm" style={{ marginRight: 8 }} disabled={isCancelling} onClick={cancelEnrollment}>
              {isCancelling ? "Cancelling…" : "Cancel cadence"}
            </button>
          </RoleOnly>
        )}
        {detail && (
          <Badge
            variant={
              detail.enrollment.status === "ACTIVE" ? "blue"
                : detail.enrollment.status === "CANCELLED" ? "red"
                : "green"
            }
          >
            {detail.enrollment.status}
          </Badge>
        )}
      </div>
      <div className="card-pad">
        {detail === undefined && <div className="t-muted">Loading…</div>}

        {detail === null && (
          <>
            <div className="t-muted" style={{ marginBottom: 14 }}>Not enrolled in a cadence yet.</div>
            <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
              <button className="btn primary sm" onClick={() => setShowEnroll(true)}>Enroll in cadence</button>
            </RoleOnly>
          </>
        )}

        {detail && (
          <>
            <div className="help" style={{ marginBottom: 14 }}>
              {detail.enrollment.status === "ACTIVE" ? "Active cadence: " : "Cadence: "}
              {template?.name ?? "Cadence"} — step {detail.enrollment.current_step_order} of {template?.steps.length ?? "—"}
            </div>
            {actionError && <div className="help err" style={{ marginBottom: 14 }}>{actionError}</div>}
            <div className="timeline">
              {tasks.map((t) => (
                <div key={t.id} className={`tl-item${t.status !== "PENDING" ? " done" : ""}`}>
                  <div className="tl-t">
                    <Badge variant={STEP_TYPE_BADGE[t.step_type] ?? "gray"} style={{ marginRight: 6 }}>{t.step_type}</Badge>
                    {t.subject}
                    {t.status === "SKIPPED" && <Badge variant="amber" style={{ marginLeft: 6 }}>Skipped</Badge>}
                    {t.auto_resolved && <Badge variant="gray" style={{ marginLeft: 6 }}>Auto</Badge>}
                  </div>
                  <div className="tl-d">
                    Due {formatDate(t.due_date)}
                    {t.status === "PENDING" && relativeDueLabel(t.due_date) && ` (${relativeDueLabel(t.due_date)})`}
                    {t.completed_at && t.status !== "PENDING" && ` · resolved ${formatDate(t.completed_at)}`}
                  </div>
                  {t.notes && <div className="tl-d">{t.notes}</div>}
                  {t.status === "SKIPPED" && detail.enrollment.status !== "CANCELLED" && (
                    <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
                      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                        <button className="btn sm" disabled={isPending} onClick={() => reopenTask(t.id)}>
                          Reopen
                        </button>
                      </div>
                    </RoleOnly>
                  )}
                  {t.status === "PENDING" && (
                    <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
                      <div style={{ marginTop: 8 }}>
                        <textarea
                          className="inp"
                          rows={2}
                          placeholder="Notes (optional)…"
                          value={notesByTask[t.id] ?? ""}
                          onChange={(e) => setNotesByTask({ ...notesByTask, [t.id]: e.target.value })}
                        />
                        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                          <button className="btn primary sm" disabled={isPending} onClick={() => respondToTask(t.id, "DONE")}>
                            Complete
                          </button>
                          <button className="btn sm" disabled={isPending} onClick={() => respondToTask(t.id, "SKIPPED")}>
                            Skip
                          </button>
                        </div>
                      </div>
                    </RoleOnly>
                  )}
                </div>
              ))}
            </div>
            {detail.enrollment.status !== "ACTIVE" && (
              <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
                <button className="btn sm" style={{ marginTop: 14 }} onClick={() => setShowEnroll(true)}>
                  Enroll in another cadence
                </button>
              </RoleOnly>
            )}
          </>
        )}
      </div>
      <EnrollCadenceModal
        open={showEnroll}
        leadId={leadId}
        onClose={() => setShowEnroll(false)}
        onEnrolled={load}
      />
    </div>
  );
}
