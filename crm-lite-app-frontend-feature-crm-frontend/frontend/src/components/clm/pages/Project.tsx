"use client";

import { useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import Badge, { type BadgeVariant } from "../Badge";
import Modal from "../Modal";
import RoleOnly from "../RoleOnly";
import Spinner from "../Spinner";
import { Icon } from "../icons";
import { useEmployeeDirectory } from "@/lib/api/identity";
import { ApiError, useApi } from "@/lib/api/client";
import { getAccount, type AccountOut } from "@/lib/api/crm";
import { getProject, updateProject, type ProjectOut } from "@/lib/api/project";

const STATUS_BADGE: Record<string, BadgeVariant> = {
  PLANNING: "blue",
  ACTIVE: "green",
  CLOSED: "gray",
};

const STATUS_OPTIONS = ["PLANNING", "ACTIVE", "CLOSED"];

function formatDate(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export default function Project({ id }: { id: string }) {
  const api = useApi();
  const { label: employeeLabel } = useEmployeeDirectory();
  const router = useRouter();
  const [project, setProject] = useState<ProjectOut | null>(null);
  const [account, setAccount] = useState<AccountOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusOpen, setStatusOpen] = useState(false);
  const [statusValue, setStatusValue] = useState("");
  const [actualEndDate, setActualEndDate] = useState("");
  const [statusError, setStatusError] = useState<string | null>(null);
  const [isSavingStatus, startSavingStatus] = useTransition();

  useEffect(() => {
    let cancelled = false;
    setProject(null);
    setError(null);
    getProject(api, id)
      .then((proj) => {
        if (cancelled) return;
        setProject(proj);
        return getAccount(api, proj.account_id).then((c) => {
          if (!cancelled) setAccount(c);
        });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Failed to load project.");
      });
    return () => {
      cancelled = true;
    };
  }, [api, id]);

  if (error) {
    return (
      <section className="page active">
        <div className="help err">{error}</div>
      </section>
    );
  }

  if (!project) {
    return (
      <section className="page active">
        <div className="card card-pad loading-inline"><Spinner /> Loading project…</div>
      </section>
    );
  }

  const accountName = account?.legal_name?.replace(/ Pvt\. Ltd\.$/, "") ?? project.account_id;

  function goBack() {
    if (typeof window !== "undefined" && window.history.length > 1) router.back();
    else router.push("/projects");
  }

  function openStatusEdit() {
    if (!project) return;
    setStatusValue(project.status);
    setActualEndDate(project.actual_end_date ?? "");
    setStatusError(null);
    setStatusOpen(true);
  }

  function saveStatus() {
    if (!project) return;
    startSavingStatus(async () => {
      try {
        const updated = await updateProject(api, project.id, {
          status: statusValue,
          actual_end_date: actualEndDate || null,
        });
        setProject(updated);
        setStatusOpen(false);
      } catch (err) {
        setStatusError(err instanceof ApiError ? err.message : "Failed to update status.");
      }
    });
  }

  return (
    <section className="page active">
      <div className="banner">
        <button type="button" onClick={goBack} className="banner-back" aria-label="Go back" title="Go back">
          <Icon name="chevronLeft" />
        </button>
        <div>
          <div className="id">{project.id} · {accountName}</div>
          <h1>{project.name}</h1>
        </div>
        <div className="spacer" />
        <span className="badge">
          <span className="dot" />
          {project.status}
        </span>
      </div>
      <div className="card card-pad">
        <div className="fields">
          <div className="field"><div className="lab">Project name <span className="req">*</span></div><div className="val">{project.name}</div></div>
          <div className="field"><div className="lab">Account <span className="req">*</span></div><div className="val">{accountName}</div></div>
          <div className="field"><div className="lab">Status <span className="req">*</span></div><div className="val"><Badge variant={STATUS_BADGE[project.status] ?? "gray"}>{project.status}</Badge></div></div>
          <div className="field"><div className="lab">Account executive</div><div className="val">{employeeLabel(project.account_executive_employee_id)}</div></div>
          <div className="field"><div className="lab">Won from</div><div className="val">{project.opportunity_id ?? "—"}</div></div>
          <div className="field"><div className="lab">Start date</div><div className="val">{formatDate(project.start_date)}</div></div>
          <div className="field"><div className="lab">Target end</div><div className="val">{formatDate(project.target_end_date)}</div></div>
          <div className="field"><div className="lab">Actual end</div><div className="val">{project.actual_end_date ? formatDate(project.actual_end_date) : <span className="empty-hint">— in progress</span>}</div></div>
        </div>
        <RoleOnly roles={["ACCOUNT_EXEC", "ADMIN"]}>
          <div style={{ marginTop: 18, paddingTop: 16, borderTop: "1px solid var(--border)" }}>
            <button className="btn sm" onClick={openStatusEdit}>Change status</button>
          </div>
        </RoleOnly>
      </div>

      <Modal
        open={statusOpen}
        onClose={() => setStatusOpen(false)}
        title="Change project status"
        footer={
          <>
            <button className="btn sm" onClick={() => setStatusOpen(false)} disabled={isSavingStatus}>Cancel</button>
            <div className="spacer" />
            <button className="btn primary sm" onClick={saveStatus} disabled={isSavingStatus}>{isSavingStatus ? "Saving…" : "Save"}</button>
          </>
        }
      >
        <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
          <div className="field">
            <div className="lab">Status <span className="req">*</span></div>
            <select className="inp" value={statusValue} onChange={(e) => setStatusValue(e.target.value)}>
              {STATUS_OPTIONS.map((o) => (
                <option key={o} value={o}>{o}</option>
              ))}
            </select>
          </div>
          {statusValue === "CLOSED" && (
            <div className="field">
              <div className="lab">Actual end date</div>
              <input className="inp" type="date" value={actualEndDate} onChange={(e) => setActualEndDate(e.target.value)} />
            </div>
          )}
          {statusError && <div className="help err">{statusError}</div>}
        </div>
      </Modal>
    </section>
  );
}
