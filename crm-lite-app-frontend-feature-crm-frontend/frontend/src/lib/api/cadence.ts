import { ApiError, type Api } from "./client";

/** Wire types for the Sales Cadence engine (src/models/crm_models.py). */
export interface CadenceStepOut {
  id: string;
  cadence_template_id: string;
  step_order: number;
  step_type: string; // CALL | EMAIL | LINKEDIN | BREAK | FOLLOW_UP | OTHER
  subject: string;
  instructions: string | null;
  wait_days: number;
  // If true, wait_days counts Mon-Fri business days only (see
  // crm_service._compute_due_date()); Sat/Sun are never counted or landed on.
  skip_weekends: boolean;
}

export interface CadenceTemplateOut {
  id: string;
  name: string;
  description: string | null;
  is_active: boolean;
  steps: CadenceStepOut[];
}

export interface CadenceTaskOut {
  id: string;
  enrollment_id: string;
  cadence_step_id: string;
  lead_id: string;
  step_type: string;
  subject: string;
  due_date: string;
  status: string; // PENDING | DONE | SKIPPED
  completed_at: string | null;
  notes: string | null;
  // True only when the scheduler (POST /cadence/advance-due-steps) resolved
  // this task itself -- a due BREAK, or a FOLLOW_UP auto-skipped because the
  // lead already replied -- rather than a rep completing/skipping it by hand.
  auto_resolved: boolean;
}

export interface LeadCadenceEnrollmentOut {
  id: string;
  lead_id: string;
  cadence_template_id: string;
  status: string; // ACTIVE | COMPLETED | CANCELLED
  current_step_order: number;
  enrolled_at: string;
  completed_at: string | null;
  enrolled_by: string | null;
}

export interface LeadCadenceDetailOut {
  enrollment: LeadCadenceEnrollmentOut;
  tasks: CadenceTaskOut[];
}

export const CADENCE_STEP_TYPES =
  ["CALL", "EMAIL", "LINKEDIN", "BREAK", "FOLLOW_UP", "OTHER"] as const;

export interface CadenceTemplateCreatePayload {
  name: string;
  description?: string | null;
}

export type CadenceTemplateUpdatePayload = Partial<CadenceTemplateCreatePayload> & { is_active?: boolean };

export interface CadenceStepCreatePayload {
  step_order: number;
  step_type: string;
  subject: string;
  instructions?: string | null;
  wait_days: number;
  skip_weekends?: boolean;
}

export type CadenceStepUpdatePayload = Partial<CadenceStepCreatePayload>;

export function listCadenceTemplates(api: Api): Promise<CadenceTemplateOut[]> {
  return api.get<CadenceTemplateOut[]>("/cadence-templates");
}

export function getCadenceTemplate(api: Api, templateId: string): Promise<CadenceTemplateOut> {
  return api.get<CadenceTemplateOut>(`/cadence-templates/${templateId}`);
}

export function createCadenceTemplate(
  api: Api,
  payload: CadenceTemplateCreatePayload
): Promise<CadenceTemplateOut> {
  return api.post<CadenceTemplateOut>("/cadence-templates", payload);
}

export function updateCadenceTemplate(
  api: Api,
  templateId: string,
  patch: CadenceTemplateUpdatePayload
): Promise<CadenceTemplateOut> {
  return api.patch<CadenceTemplateOut>(`/cadence-templates/${templateId}`, patch);
}

export function addCadenceStep(
  api: Api,
  templateId: string,
  payload: CadenceStepCreatePayload
): Promise<CadenceStepOut> {
  return api.post<CadenceStepOut>(`/cadence-templates/${templateId}/steps`, payload);
}

export function updateCadenceStep(
  api: Api,
  stepId: string,
  patch: CadenceStepUpdatePayload
): Promise<CadenceStepOut> {
  return api.patch<CadenceStepOut>(`/cadence-steps/${stepId}`, patch);
}

export function deleteCadenceStep(api: Api, stepId: string): Promise<void> {
  return api.del(`/cadence-steps/${stepId}`);
}

/** Returns null when the lead has never been enrolled in a cadence (backend
 * 404s LEAD_HAS_NO_CADENCE_ENROLLMENT in that case). */
export function getLeadCadence(api: Api, leadId: string): Promise<LeadCadenceDetailOut | null> {
  return api.get<LeadCadenceDetailOut>(`/leads/${leadId}/cadence`).catch((err) => {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  });
}

export function enrollLeadInCadence(
  api: Api,
  leadId: string,
  cadenceTemplateId: string
): Promise<LeadCadenceDetailOut> {
  return api.post<LeadCadenceDetailOut>(`/leads/${leadId}/cadence/enroll`, {
    cadence_template_id: cadenceTemplateId,
  });
}

export function cancelLeadCadence(api: Api, leadId: string): Promise<LeadCadenceDetailOut> {
  return api.post<LeadCadenceDetailOut>(`/leads/${leadId}/cadence/cancel`);
}

/** Every pending cadence task across every lead this caller owns — feeds
 * the personal rep dashboard. See crm_service.list_my_cadence_tasks(): uses
 * literal ownership only (not Role Hierarchy subordinates), so a manager's
 * "my tasks" never includes their reports'. */
export function listMyCadenceTasks(api: Api): Promise<CadenceTaskOut[]> {
  return api.get<CadenceTaskOut[]>("/cadence-tasks/my");
}

export function completeCadenceTask(api: Api, taskId: string, notes?: string): Promise<CadenceTaskOut> {
  return api.post<CadenceTaskOut>(`/cadence-tasks/${taskId}/complete`, {
    outcome_status: "DONE",
    notes: notes || null,
  });
}

export function skipCadenceTask(api: Api, taskId: string, notes?: string): Promise<CadenceTaskOut> {
  return api.post<CadenceTaskOut>(`/cadence-tasks/${taskId}/complete`, {
    outcome_status: "SKIPPED",
    notes: notes || null,
  });
}

/** SKIPPED -> PENDING on the same task (no new task, no other task touched).
 * Resolve it again afterwards with completeCadenceTask()/skipCadenceTask(). */
export function reopenCadenceTask(api: Api, taskId: string): Promise<CadenceTaskOut> {
  return api.post<CadenceTaskOut>(`/cadence-tasks/${taskId}/reopen`);
}
