"use client";

import { useEffect, useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import RoleOnly from "../RoleOnly";
import Badge, { type BadgeVariant } from "../Badge";
import Modal from "../Modal";
import AssignOwnerModal from "../AssignOwnerModal";
import Spinner from "../Spinner";
import { Icon } from "../icons";
import { OPPORTUNITY_STAGES } from "@/lib/seed/lookups";
import { useEmployeeDirectory } from "@/lib/api/identity";
import { ApiError, useApi } from "@/lib/api/client";
import { useAppSelector } from "@/lib/hooks";
import {
  addOpportunityDocument,
  deleteOpportunity,
  getCampaign,
  getAccount,
  getOpportunity,
  listOpportunityDocuments,
  updateOpportunity,
  type CampaignOut,
  type AccountOut,
  type OpportunityDocumentOut,
  type OpportunityOut,
} from "@/lib/api/crm";
import { createProject, listProjects, type ProjectOut } from "@/lib/api/project";
import { useFieldPermissions } from "@/lib/api/fieldPermissions";

const DOC_STATUS_BADGE: Record<string, BadgeVariant> = {
  DRAFT: "gray",
  UPLOADED: "blue",
  SENT: "amber",
  ACCEPTED: "green",
  REJECTED: "red",
};

const PIPELINE_STAGES = OPPORTUNITY_STAGES.filter((s) => s.code !== "LOST");
const OPPORTUNITY_TYPES = ["", "NEW_BUSINESS", "EXISTING_BUSINESS", "RENEWAL"];

export default function Opportunity({ id }: { id: string }) {
  const api = useApi();
  const { label: employeeLabel } = useEmployeeDirectory();
  const { isVisible, isEditable } = useFieldPermissions("OPPORTUNITY");
  const role = useAppSelector((state) => state.role.value);
  const canEditOpportunity = (["SALES", "ACCOUNT_EXEC", "ADMIN"] as string[]).includes(role);
  const router = useRouter();
  const [loadedId, setLoadedId] = useState<string | null>(null);
  const [opportunity, setOpportunity] = useState<OpportunityOut | null>(null);
  const [account, setAccount] = useState<AccountOut | null>(null);
  const [sourceCampaign, setSourceCampaign] = useState<CampaignOut | null>(null);
  const [existingProject, setExistingProject] = useState<ProjectOut | null>(null);
  const [documents, setDocuments] = useState<OpportunityDocumentOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [showAssignOwner, setShowAssignOwner] = useState(false);
  const [showMarkLost, setShowMarkLost] = useState(false);
  const [lostReason, setLostReason] = useState("");
  const [lostReasonError, setLostReasonError] = useState<string | null>(null);
  const [showStartProject, setShowStartProject] = useState(false);
  const [projectName, setProjectName] = useState("");
  const [projectStartDate, setProjectStartDate] = useState("");
  const [projectError, setProjectError] = useState<string | null>(null);
  const [showAttachDoc, setShowAttachDoc] = useState(false);
  const [docFilename, setDocFilename] = useState("");
  const [docSharepointUrl, setDocSharepointUrl] = useState("");
  const [docError, setDocError] = useState<string | null>(null);
  const [editingDetails, setEditingDetails] = useState(false);
  const [detailsDraft, setDetailsDraft] = useState({
    name: "",
    estimated_value: "",
    currency: "",
    expected_close_date: "",
    probability_percent: "",
    opportunity_type: "",
    next_step: "",
    description: "",
  });
  const [detailsError, setDetailsError] = useState<string | null>(null);
  const [isUpdating, startUpdate] = useTransition();
  const [isStartingProject, startProjectTransition] = useTransition();
  const [isAttachingDoc, startAttachingDoc] = useTransition();

  if (loadedId !== id) {
    setLoadedId(id);
    setOpportunity(null);
    setError(null);
  }

  useEffect(() => {
    let cancelled = false;
    Promise.all([getOpportunity(api, id), listProjects(api), listOpportunityDocuments(api, id)])
      .then(([opp, allProjects, docs]) => {
        if (cancelled) return;
        setOpportunity(opp);
        setExistingProject(allProjects.find((p) => p.opportunity_id === id) ?? null);
        setDocuments(docs);
        if (opp.campaign_id) {
          getCampaign(api, opp.campaign_id).then((c) => {
            if (!cancelled) setSourceCampaign(c);
          }).catch(() => {
            /* attribution is a nice-to-have — a missing/deleted campaign shouldn't break the page */
          });
        }
        return getAccount(api, opp.account_id).then((c) => {
          if (!cancelled) setAccount(c);
        });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Failed to load opportunity.");
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

  if (!opportunity) {
    return (
      <section className="page active">
        <div className="card card-pad loading-inline"><Spinner /> Loading opportunity…</div>
      </section>
    );
  }

  const stage = OPPORTUNITY_STAGES.find((s) => s.code === opportunity.stage);
  const sortedDocuments = [...documents].sort((a, b) => b.version_number - a.version_number);
  const isLost = opportunity.stage === "LOST";
  const accountName = account?.legal_name?.replace(/ Pvt\. Ltd\.$/, "") ?? opportunity.account_id;

  const stageIndex = PIPELINE_STAGES.findIndex((s) => s.code === opportunity.stage);
  const nextStage = stageIndex >= 0 && stageIndex < PIPELINE_STAGES.length - 1 ? PIPELINE_STAGES[stageIndex + 1] : null;

  function advanceStage() {
    if (!nextStage) return;
    setActionError(null);
    startUpdate(async () => {
      try {
        const updated = await updateOpportunity(api, id, { stage: nextStage.code });
        setOpportunity(updated);
      } catch (err) {
        setActionError(err instanceof ApiError ? err.message : "Failed to advance stage.");
      }
    });
  }

  function openEditDetails() {
    if (!opportunity) return;
    setDetailsDraft({
      name: opportunity.name ?? "",
      estimated_value: opportunity.estimated_value != null ? String(opportunity.estimated_value) : "",
      currency: opportunity.currency ?? "",
      expected_close_date: opportunity.expected_close_date ?? "",
      probability_percent: opportunity.probability_percent != null ? String(opportunity.probability_percent) : "",
      opportunity_type: opportunity.opportunity_type ?? "",
      next_step: opportunity.next_step ?? "",
      description: opportunity.description ?? "",
    });
    setDetailsError(null);
    setEditingDetails(true);
  }

  function saveDetails() {
    if (!detailsDraft.name.trim()) {
      setDetailsError("Deal name is required.");
      return;
    }
    setActionError(null);
    startUpdate(async () => {
      try {
        const updated = await updateOpportunity(api, id, {
          name: detailsDraft.name.trim(),
          estimated_value: detailsDraft.estimated_value.trim() ? Number(detailsDraft.estimated_value) : null,
          currency: detailsDraft.currency.trim() || undefined,
          expected_close_date: detailsDraft.expected_close_date || null,
          probability_percent: detailsDraft.probability_percent.trim() ? Number(detailsDraft.probability_percent) : null,
          opportunity_type: detailsDraft.opportunity_type || null,
          next_step: detailsDraft.next_step.trim() || null,
          description: detailsDraft.description.trim() || null,
        });
        setOpportunity(updated);
        setEditingDetails(false);
      } catch (err) {
        setDetailsError(err instanceof ApiError ? err.message : "Failed to save details.");
      }
    });
  }

  function remove() {
    if (!opportunity) return;
    if (!window.confirm(`Delete the opportunity "${opportunity.name}"? This can't be undone.`)) return;
    setActionError(null);
    startUpdate(async () => {
      try {
        await deleteOpportunity(api, id);
        router.push("/opportunities");
      } catch (err) {
        setActionError(err instanceof ApiError ? err.message : "Failed to delete opportunity.");
      }
    });
  }

  async function assignOwner(ownerId: string | null) {
    const updated = await updateOpportunity(api, id, { owner_employee_id: ownerId });
    setOpportunity(updated);
  }

  function openMarkLost() {
    setLostReason("");
    setLostReasonError(null);
    setShowMarkLost(true);
  }

  function confirmMarkLost() {
    if (!lostReason.trim()) {
      setLostReasonError("A reason is required to mark this opportunity as lost.");
      return;
    }
    setActionError(null);
    startUpdate(async () => {
      try {
        const updated = await updateOpportunity(api, id, { stage: "LOST", lost_reason: lostReason.trim() });
        setOpportunity(updated);
        setShowMarkLost(false);
      } catch (err) {
        setLostReasonError(err instanceof ApiError ? err.message : "Failed to mark opportunity as lost.");
      }
    });
  }

  function openStartProject() {
    setProjectName(opportunity?.name ?? "");
    setProjectStartDate(new Date().toISOString().slice(0, 10));
    setProjectError(null);
    setShowStartProject(true);
  }

  function confirmStartProject() {
    if (!projectName.trim()) {
      setProjectError("Project name is required.");
      return;
    }
    if (!projectStartDate) {
      setProjectError("Start date is required.");
      return;
    }
    startProjectTransition(async () => {
      try {
        const created = await createProject(api, {
          opportunity_id: id,
          name: projectName.trim(),
          start_date: projectStartDate,
        });
        router.push(`/projects/${created.id}`);
      } catch (err) {
        setProjectError(err instanceof ApiError ? err.message : "Failed to start project.");
      }
    });
  }

  function openAttachDoc() {
    setDocFilename("");
    setDocSharepointUrl("");
    setDocError(null);
    setShowAttachDoc(true);
  }

  function confirmAttachDoc() {
    if (!docFilename.trim()) {
      setDocError("Filename is required.");
      return;
    }
    startAttachingDoc(async () => {
      try {
        const created = await addOpportunityDocument(api, id, {
          doc_type: "PROPOSAL",
          filename: docFilename.trim(),
          sharepoint_url: docSharepointUrl.trim() || null,
        });
        setDocuments((prev) => [...prev, created]);
        setShowAttachDoc(false);
      } catch (err) {
        setDocError(err instanceof ApiError ? err.message : "Failed to attach document.");
      }
    });
  }

  function goBack() {
    if (typeof window !== "undefined" && window.history.length > 1) router.back();
    else router.push("/opportunities");
  }

  return (
    <section className="page active">
      <div className="banner">
        <button type="button" onClick={goBack} className="banner-back" aria-label="Go back" title="Go back">
          <Icon name="chevronLeft" />
        </button>
        <div>
          <div className="id">{opportunity.id} · {accountName}</div>
          <h1>{opportunity.name}</h1>
        </div>
        <div className="spacer" />
        {opportunity.stage === "WON" && (
          <RoleOnly roles={["ACCOUNT_EXEC", "ADMIN"]}>
            {existingProject ? (
              <Link href={`/projects/${existingProject.id}`} className="btn sm" style={{ marginRight: 10 }}>
                View project
              </Link>
            ) : (
              <button className="btn primary sm" style={{ marginRight: 10 }} onClick={openStartProject}>
                Start project
              </button>
            )}
          </RoleOnly>
        )}
        {opportunity.can_delete && (
          <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
            <button className="btn sm" style={{ marginRight: 10 }} disabled={isUpdating} onClick={remove}>
              Delete
            </button>
          </RoleOnly>
        )}
        <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
          <button
            className="badge"
            style={{ cursor: "pointer", border: "none" }}
            onClick={() => setShowAssignOwner(true)}
          >
            Owner · {employeeLabel(opportunity.owner_employee_id)} · Change
          </button>
        </RoleOnly>
        {!canEditOpportunity && <span className="badge">Owner · {employeeLabel(opportunity.owner_employee_id)}</span>}
      </div>
      <div className="stagebar">
        {PIPELINE_STAGES.map((s) => (
          <div
            key={s.id}
            className={`st${s.id < (stage?.id ?? 0) ? " done" : ""}${s.id === stage?.id ? " current" : ""}`}
          >
            {s.display_name}
          </div>
        ))}
        <div className={`st${isLost ? " lost" : ""}`}>Lost</div>
      </div>
      <div className="split">
        <div className="card">
          <div className="card-head">
            <h3>Deal details</h3>
            <div className="spacer" />
            <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
              {!isLost && (
                <button className="btn primary sm" onClick={advanceStage} disabled={isUpdating || !nextStage}>
                  {nextStage ? `Advance to ${nextStage.display_name}` : "Advance stage"}
                </button>
              )}
              {!isLost && <button className="btn sm" onClick={openMarkLost} disabled={isUpdating}>Mark lost</button>}
            </RoleOnly>
          </div>
          <div className="card-pad">
            {actionError && <div className="help err" style={{ marginBottom: 14 }}>{actionError}</div>}
            <div className="fields">
              <div className="field"><div className="lab">Account <span className="req">*</span></div><div className="val">{accountName}</div></div>
              <div className="field"><div className="lab">Stage <span className="req">*</span></div><div className="val">{stage && <Badge variant="blue">{stage.display_name}</Badge>}</div></div>
              {!editingDetails && (
                <>
                  {isVisible("name") && (
                    <div className="field"><div className="lab">Deal name <span className="req">*</span></div><div className="val">{opportunity.name}</div></div>
                  )}
                  {isVisible("estimated_value") && (
                    <div className="field"><div className="lab">Estimated value</div><div className="val num">{opportunity.estimated_value != null ? `${opportunity.currency ?? "USD"} ${opportunity.estimated_value.toLocaleString()}` : "—"}</div></div>
                  )}
                  {isVisible("currency") && (
                    <div className="field"><div className="lab">Currency</div><div className="val">{opportunity.currency ?? "—"}</div></div>
                  )}
                  {isVisible("expected_close_date") && (
                    <div className="field"><div className="lab">Expected close</div><div className="val">{opportunity.expected_close_date ? new Date(opportunity.expected_close_date).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "—"}</div></div>
                  )}
                </>
              )}
              {isLost && isVisible("lost_reason") && (
                <div className="field"><div className="lab">Lost reason</div><div className="val">{opportunity.lost_reason || "—"}</div></div>
              )}
              {opportunity.campaign_id && (
                <div className="field">
                  <div className="lab">Source campaign</div>
                  <div className="val">
                    {sourceCampaign ? <Badge variant="teal">{sourceCampaign.name}</Badge> : opportunity.campaign_id}
                  </div>
                </div>
              )}
              {!editingDetails && (
                <>
                  {isVisible("probability_percent") && (
                    <div className="field"><div className="lab">Probability %</div><div className="val num">{opportunity.probability_percent != null ? `${opportunity.probability_percent}%` : "—"}</div></div>
                  )}
                  {isVisible("opportunity_type") && (
                    <div className="field"><div className="lab">Opportunity type</div><div className="val">{opportunity.opportunity_type ? opportunity.opportunity_type.replace("_", " ") : "—"}</div></div>
                  )}
                  {isVisible("next_step") && (
                    <div className="field"><div className="lab">Next step</div><div className="val">{opportunity.next_step || "—"}</div></div>
                  )}
                  {isVisible("description") && (
                    <div className="field"><div className="lab">Description</div><div className="val">{opportunity.description || "—"}</div></div>
                  )}
                </>
              )}
            </div>
            {editingDetails ? (
              <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--border)" }}>
                <div className="fields" style={{ gridTemplateColumns: "repeat(2, 1fr)" }}>
                  {isVisible("name") && (
                    <div className="field" style={{ gridColumn: "1 / -1" }}>
                      <div className="lab">Deal name <span className="req">*</span></div>
                      <input
                        className="inp"
                        disabled={!isEditable("name")}
                        value={detailsDraft.name}
                        onChange={(e) => setDetailsDraft({ ...detailsDraft, name: e.target.value })}
                      />
                    </div>
                  )}
                  {isVisible("estimated_value") && (
                    <div className="field">
                      <div className="lab">Estimated value</div>
                      <input
                        className="inp"
                        type="number"
                        disabled={!isEditable("estimated_value")}
                        value={detailsDraft.estimated_value}
                        onChange={(e) => setDetailsDraft({ ...detailsDraft, estimated_value: e.target.value })}
                      />
                    </div>
                  )}
                  {isVisible("currency") && (
                    <div className="field">
                      <div className="lab">Currency</div>
                      <input
                        className="inp"
                        disabled={!isEditable("currency")}
                        value={detailsDraft.currency}
                        onChange={(e) => setDetailsDraft({ ...detailsDraft, currency: e.target.value })}
                        placeholder="USD"
                      />
                    </div>
                  )}
                  {isVisible("expected_close_date") && (
                    <div className="field">
                      <div className="lab">Expected close</div>
                      <input
                        type="date"
                        className="inp"
                        disabled={!isEditable("expected_close_date")}
                        value={detailsDraft.expected_close_date}
                        onChange={(e) => setDetailsDraft({ ...detailsDraft, expected_close_date: e.target.value })}
                      />
                    </div>
                  )}
                  {isVisible("probability_percent") && (
                    <div className="field">
                      <div className="lab">Probability %</div>
                      <input
                        className="inp"
                        type="number"
                        disabled={!isEditable("probability_percent")}
                        value={detailsDraft.probability_percent}
                        onChange={(e) => setDetailsDraft({ ...detailsDraft, probability_percent: e.target.value })}
                      />
                    </div>
                  )}
                  {isVisible("opportunity_type") && (
                    <div className="field">
                      <div className="lab">Opportunity type</div>
                      <select
                        className="inp"
                        disabled={!isEditable("opportunity_type")}
                        value={detailsDraft.opportunity_type}
                        onChange={(e) => setDetailsDraft({ ...detailsDraft, opportunity_type: e.target.value })}
                      >
                        {OPPORTUNITY_TYPES.map((t) => <option key={t} value={t}>{t ? t.replace("_", " ") : "—"}</option>)}
                      </select>
                    </div>
                  )}
                  {isVisible("next_step") && (
                    <div className="field" style={{ gridColumn: "1 / -1" }}>
                      <div className="lab">Next step</div>
                      <input
                        className="inp"
                        disabled={!isEditable("next_step")}
                        value={detailsDraft.next_step}
                        onChange={(e) => setDetailsDraft({ ...detailsDraft, next_step: e.target.value })}
                      />
                    </div>
                  )}
                  {isVisible("description") && (
                    <div className="field" style={{ gridColumn: "1 / -1" }}>
                      <div className="lab">Description</div>
                      <textarea
                        className="inp"
                        rows={3}
                        disabled={!isEditable("description")}
                        value={detailsDraft.description}
                        onChange={(e) => setDetailsDraft({ ...detailsDraft, description: e.target.value })}
                      />
                    </div>
                  )}
                </div>
                {detailsError && <div className="help err" style={{ marginTop: 10 }}>{detailsError}</div>}
                <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
                  <button className="btn primary sm" onClick={saveDetails} disabled={isUpdating}>
                    {isUpdating ? "Saving…" : "Save"}
                  </button>
                  <button className="btn sm" onClick={() => setEditingDetails(false)} disabled={isUpdating}>Cancel</button>
                </div>
              </div>
            ) : (
              <div className="help" style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 10 }}>
                <span>Validation — moving to “Lost” requires a lost reason.</span>
                <div className="spacer" />
                {opportunity.can_edit && (
                  <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
                    <button className="btn sm" onClick={openEditDetails}>Edit details</button>
                  </RoleOnly>
                )}
              </div>
            )}
          </div>
        </div>
        <div className="card">
          <div className="card-head"><h3>Proposal</h3></div>
          <table>
            <thead><tr><th>Ver</th><th>Type</th><th>Status</th></tr></thead>
            <tbody>
              {sortedDocuments.map((doc) => (
                <tr key={doc.id}>
                  <td className="t-strong">v{doc.version_number}</td>
                  <td>{doc.doc_type === "PROPOSAL" ? "Proposal" : doc.doc_type === "QUOTE" ? "Quote" : "—"}</td>
                  <td>
                    {doc.status ? (
                      <Badge variant={DOC_STATUS_BADGE[doc.status] ?? "gray"}>
                        {doc.status.charAt(0) + doc.status.slice(1).toLowerCase()}
                      </Badge>
                    ) : "—"}
                  </td>
                </tr>
              ))}
              {sortedDocuments.length === 0 && (
                <tr>
                  <td colSpan={3} className="empty-hint" style={{ padding: "18px 22px" }}>No documents yet.</td>
                </tr>
              )}
            </tbody>
          </table>
          <RoleOnly roles={["SALES", "ACCOUNT_EXEC", "ADMIN"]}>
            <div className="card-pad" style={{ borderTop: "1px solid var(--border)" }}>
              <button className="btn sm" style={{ width: "100%", justifyContent: "center" }} onClick={openAttachDoc}>
                Attach new version
              </button>
            </div>
          </RoleOnly>
        </div>
      </div>
      <Modal
        open={showAttachDoc}
        onClose={() => setShowAttachDoc(false)}
        title="Attach new proposal version"
        footer={
          <>
            <button className="btn sm" onClick={() => setShowAttachDoc(false)} disabled={isAttachingDoc}>Cancel</button>
            <div className="spacer" />
            <button className="btn primary sm" onClick={confirmAttachDoc} disabled={isAttachingDoc}>
              {isAttachingDoc ? "Attaching…" : "Attach"}
            </button>
          </>
        }
      >
        <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
          <div className="field">
            <div className="lab">Filename <span className="req">*</span></div>
            <input className="inp" value={docFilename} onChange={(e) => setDocFilename(e.target.value)} autoFocus />
            {docError && <div className="help err">{docError}</div>}
          </div>
          <div className="field">
            <div className="lab">SharePoint URL</div>
            <input className="inp" value={docSharepointUrl} onChange={(e) => setDocSharepointUrl(e.target.value)} />
          </div>
        </div>
      </Modal>
      <Modal
        open={showMarkLost}
        onClose={() => setShowMarkLost(false)}
        title="Mark opportunity as lost"
        footer={
          <>
            <button className="btn sm" onClick={() => setShowMarkLost(false)} disabled={isUpdating}>Cancel</button>
            <div className="spacer" />
            <button className="btn primary sm" onClick={confirmMarkLost} disabled={isUpdating}>
              {isUpdating ? "Saving…" : "Mark lost"}
            </button>
          </>
        }
      >
        <div className="field">
          <div className="lab">Lost reason <span className="req">*</span></div>
          <textarea
            className="inp"
            rows={4}
            value={lostReason}
            onChange={(e) => setLostReason(e.target.value)}
            autoFocus
          />
          {lostReasonError && <div className="help err">{lostReasonError}</div>}
        </div>
      </Modal>
      <Modal
        open={showStartProject}
        onClose={() => setShowStartProject(false)}
        title="Start project"
        footer={
          <>
            <button className="btn sm" onClick={() => setShowStartProject(false)} disabled={isStartingProject}>Cancel</button>
            <div className="spacer" />
            <button className="btn primary sm" onClick={confirmStartProject} disabled={isStartingProject}>
              {isStartingProject ? "Starting…" : "Start project"}
            </button>
          </>
        }
      >
        <div className="fields" style={{ gridTemplateColumns: "1fr" }}>
          <div className="field">
            <div className="lab">Project name <span className="req">*</span></div>
            <input className="inp" value={projectName} onChange={(e) => setProjectName(e.target.value)} autoFocus />
          </div>
          <div className="field">
            <div className="lab">Start date <span className="req">*</span></div>
            <input
              type="date"
              className="inp"
              value={projectStartDate}
              onChange={(e) => setProjectStartDate(e.target.value)}
            />
          </div>
          {projectError && <div className="help err">{projectError}</div>}
          <div className="help">
            Starts in Planning, inheriting {accountName} as the account. Budget and SOW setup happen on the project page afterward.
          </div>
        </div>
      </Modal>
      <AssignOwnerModal
        open={showAssignOwner}
        currentOwnerId={opportunity.owner_employee_id}
        onClose={() => setShowAssignOwner(false)}
        onAssign={assignOwner}
      />
    </section>
  );
}
