"use client";

import { useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import Badge, { type BadgeVariant } from "../Badge";
import Modal from "../Modal";
import RoleOnly from "../RoleOnly";
import Spinner from "../Spinner";
import { Icon } from "../icons";
import { ApiError, useApi } from "@/lib/api/client";
import {
  CADENCE_STEP_TYPES,
  addCadenceStep,
  deleteCadenceStep,
  getCadenceTemplate,
  updateCadenceStep,
  updateCadenceTemplate,
  type CadenceStepOut,
  type CadenceTemplateOut,
} from "@/lib/api/cadence";

const STEP_TYPE_BADGE: Record<string, BadgeVariant> = {
  CALL: "teal",
  EMAIL: "blue",
  LINKEDIN: "violet",
  BREAK: "amber",
  FOLLOW_UP: "green",
  OTHER: "gray",
};

export default function CadenceTemplateDetail({ id }: { id: string }) {
  const api = useApi();
  const router = useRouter();
  const [template, setTemplate] = useState<CadenceTemplateOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showEditTemplate, setShowEditTemplate] = useState(false);
  const [showNewStep, setShowNewStep] = useState(false);
  const [editingStep, setEditingStep] = useState<CadenceStepOut | null>(null);
  const [deletingStepId, setDeletingStepId] = useState<string | null>(null);

  function load() {
    setTemplate(null);
    setError(null);
    getCadenceTemplate(api, id)
      .then(setTemplate)
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Failed to load this cadence.");
      });
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, id]);

  function goBack() {
    if (typeof window !== "undefined" && window.history.length > 1) router.back();
    else router.push("/admin/cadence-templates");
  }

  function removeStep(step: CadenceStepOut) {
    if (!template) return;
    if (!window.confirm(`Remove step "${step.subject}"?`)) return;
    setDeletingStepId(step.id);
    deleteCadenceStep(api, step.id)
      .then(() => setTemplate({ ...template, steps: template.steps.filter((s) => s.id !== step.id) }))
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Failed to remove step.");
      })
      .finally(() => setDeletingStepId(null));
  }

  if (error && !template) {
    return (
      <section className="page active">
        <div className="help err">{error}</div>
      </section>
    );
  }

  if (!template) {
    return (
      <section className="page active">
        <div className="card card-pad loading-inline"><Spinner /> Loading…</div>
      </section>
    );
  }

  return (
    <section className="page active">
      <div className="banner">
        <button type="button" onClick={goBack} className="banner-back" aria-label="Go back" title="Go back">
          <Icon name="chevronLeft" />
        </button>
        <div>
          <div className="id">Sales cadence</div>
          <h1>{template.name}</h1>
        </div>
        <div className="spacer" />
        <Badge variant={template.is_active ? "green" : "gray"} style={{ marginRight: 8 }}>
          {template.is_active ? "Active" : "Inactive"}
        </Badge>
        <RoleOnly roles={["ADMIN"]}>
          <button className="btn sm" onClick={() => setShowEditTemplate(true)}>Edit</button>
        </RoleOnly>
      </div>

      {error && <div className="help err" style={{ margin: "12px 0" }}>{error}</div>}

      {template.description && (
        <div className="card card-pad" style={{ marginBottom: 16 }}>
          <div className="lab">Description</div>
          <div className="val">{template.description}</div>
        </div>
      )}

      <div className="card">
        <div className="card-head">
          <h3>Steps</h3>
          <div className="spacer" />
          <RoleOnly roles={["ADMIN"]}>
            <button className="btn sm" onClick={() => setShowNewStep(true)}>Add step</button>
          </RoleOnly>
        </div>
        <table>
          <thead>
            <tr>
              <th>Step</th>
              <th>Type</th>
              <th>Subject</th>
              <th>Instructions</th>
              <th>Wait (days)</th>
              <th>Skip weekends</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {[...template.steps]
              .sort((a, b) => a.step_order - b.step_order)
              .map((step) => (
                <tr key={step.id}>
                  <td className="num">{step.step_order}</td>
                  <td><Badge variant={STEP_TYPE_BADGE[step.step_type] ?? "gray"}>{step.step_type}</Badge></td>
                  <td>{step.subject}</td>
                  <td className="t-muted">{step.instructions ?? "—"}</td>
                  <td className="num">{step.wait_days}</td>
                  <td>{step.skip_weekends ? "Yes" : "No"}</td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    <RoleOnly roles={["ADMIN"]}>
                      <button className="btn sm" onClick={() => setEditingStep(step)}>Edit</button>{" "}
                      <button
                        className="btn sm"
                        disabled={deletingStepId === step.id}
                        onClick={() => removeStep(step)}
                      >
                        {deletingStepId === step.id ? "Removing…" : "Remove"}
                      </button>
                    </RoleOnly>
                  </td>
                </tr>
              ))}
            {template.steps.length === 0 && (
              <tr>
                <td colSpan={7} className="empty-hint">No steps configured.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <EditTemplateModal
        open={showEditTemplate}
        template={template}
        onClose={() => setShowEditTemplate(false)}
        onSaved={(updated) => setTemplate({ ...updated, steps: template.steps })}
      />
      <StepModal
        mode="new"
        open={showNewStep}
        template={template}
        step={null}
        onClose={() => setShowNewStep(false)}
        onSaved={(step) => setTemplate({ ...template, steps: [...template.steps, step] })}
      />
      <StepModal
        mode="edit"
        open={editingStep !== null}
        template={template}
        step={editingStep}
        onClose={() => setEditingStep(null)}
        onSaved={(step) =>
          setTemplate({ ...template, steps: template.steps.map((s) => (s.id === step.id ? step : s)) })
        }
      />
    </section>
  );
}

function EditTemplateModal({
  open,
  template,
  onClose,
  onSaved,
}: {
  open: boolean;
  template: CadenceTemplateOut;
  onClose: () => void;
  onSaved: (template: CadenceTemplateOut) => void;
}) {
  const api = useApi();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    if (!open) return;
    setName(template.name);
    setDescription(template.description ?? "");
    setIsActive(template.is_active);
    setError(null);
  }, [open, template]);

  function submit() {
    if (!name.trim()) {
      setError("Name is required.");
      return;
    }
    startTransition(async () => {
      try {
        const updated = await updateCadenceTemplate(api, template.id, {
          name: name.trim(),
          description: description.trim() || null,
          is_active: isActive,
        });
        onSaved(updated);
        onClose();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to save cadence.");
      }
    });
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Edit ${template.name}`}
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
          <div className="lab">Name <span className="req">*</span></div>
          <input className="inp" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        </div>
        <div className="field">
          <div className="lab">Description</div>
          <textarea className="inp" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
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

function StepModal({
  mode,
  open,
  template,
  step,
  onClose,
  onSaved,
}: {
  mode: "new" | "edit";
  open: boolean;
  template: CadenceTemplateOut;
  step: CadenceStepOut | null;
  onClose: () => void;
  onSaved: (step: CadenceStepOut) => void;
}) {
  const api = useApi();
  const [stepOrder, setStepOrder] = useState("1");
  const [stepType, setStepType] = useState<string>(CADENCE_STEP_TYPES[0]);
  const [subject, setSubject] = useState("");
  const [instructions, setInstructions] = useState("");
  const [waitDays, setWaitDays] = useState("0");
  const [skipWeekends, setSkipWeekends] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    if (!open) return;
    if (mode === "edit" && step) {
      setStepOrder(String(step.step_order));
      setStepType(step.step_type);
      setSubject(step.subject);
      setInstructions(step.instructions ?? "");
      setWaitDays(String(step.wait_days));
      setSkipWeekends(step.skip_weekends);
    } else {
      setStepOrder(String(template.steps.length + 1));
      setStepType(CADENCE_STEP_TYPES[0]);
      setSubject("");
      setInstructions("");
      setWaitDays("0");
      setSkipWeekends(false);
    }
    setError(null);
  }, [open, mode, step, template.steps.length]);

  function submit() {
    if (!subject.trim()) {
      setError("Subject is required.");
      return;
    }
    const order = Number(stepOrder);
    const wait = Number(waitDays);
    if (!Number.isInteger(order) || order < 1) {
      setError("Step order must be a positive number.");
      return;
    }
    if (!Number.isInteger(wait) || wait < 0) {
      setError("Wait days must be zero or a positive number.");
      return;
    }
    startTransition(async () => {
      try {
        const payload = {
          step_order: order,
          step_type: stepType,
          subject: subject.trim(),
          instructions: instructions.trim() || null,
          wait_days: wait,
          skip_weekends: skipWeekends,
        };
        const saved =
          mode === "edit" && step
            ? await updateCadenceStep(api, step.id, payload)
            : await addCadenceStep(api, template.id, payload);
        onSaved(saved);
        onClose();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to save step.");
      }
    });
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={mode === "edit" ? "Edit step" : "Add step"}
      footer={
        <>
          <button className="btn sm" onClick={onClose} disabled={isPending}>Cancel</button>
          <div className="spacer" />
          <button className="btn primary sm" onClick={submit} disabled={isPending}>{isPending ? "Saving…" : "Save"}</button>
        </>
      }
    >
      <div className="fields" style={{ gridTemplateColumns: "1fr 1fr" }}>
        <div className="field">
          <div className="lab">Step order <span className="req">*</span></div>
          <input className="inp" type="number" min={1} value={stepOrder} onChange={(e) => setStepOrder(e.target.value)} />
        </div>
        <div className="field">
          <div className="lab">Type <span className="req">*</span></div>
          <select className="inp" value={stepType} onChange={(e) => setStepType(e.target.value)}>
            {CADENCE_STEP_TYPES.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>
        <div className="field" style={{ gridColumn: "1 / -1" }}>
          <div className="lab">Subject <span className="req">*</span></div>
          <input className="inp" value={subject} onChange={(e) => setSubject(e.target.value)} autoFocus />
        </div>
        <div className="field" style={{ gridColumn: "1 / -1" }}>
          <div className="lab">Instructions</div>
          <textarea className="inp" rows={3} value={instructions} onChange={(e) => setInstructions(e.target.value)} />
        </div>
        <div className="field">
          <div className="lab">Wait (days) <span className="req">*</span></div>
          <input className="inp" type="number" min={0} value={waitDays} onChange={(e) => setWaitDays(e.target.value)} />
        </div>
        <div className="field">
          <label className="val" style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 22 }}>
            <input
              type="checkbox"
              checked={skipWeekends}
              onChange={(e) => setSkipWeekends(e.target.checked)}
            />
            Skip weekends (business days only)
          </label>
        </div>
        {error && <div className="help err" style={{ gridColumn: "1 / -1" }}>{error}</div>}
      </div>
    </Modal>
  );
}
