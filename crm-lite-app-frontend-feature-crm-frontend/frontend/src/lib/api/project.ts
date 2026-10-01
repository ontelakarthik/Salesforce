import type { Api } from "./client";

/** Wire types for the Project module (src/models/project_models.py). */
export interface ProjectOut {
  id: string;
  account_id: string;
  opportunity_id: string | null;
  name: string;
  description: string | null;
  status: string;
  account_executive_employee_id: string | null;
  start_date: string;
  target_end_date: string | null;
  actual_end_date: string | null;
}

export interface ProjectCreatePayload {
  opportunity_id: string;
  name: string;
  description?: string | null;
  account_executive_employee_id?: string | null;
  start_date: string;
  target_end_date?: string | null;
}

export interface ProjectUpdatePayload {
  name?: string;
  description?: string | null;
  status?: string;
  account_executive_employee_id?: string | null;
  target_end_date?: string | null;
  actual_end_date?: string | null;
}

export function listProjects(api: Api): Promise<ProjectOut[]> {
  return api.get<ProjectOut[]>("/projects");
}

export function getProject(api: Api, projectId: string): Promise<ProjectOut> {
  return api.get<ProjectOut>(`/projects/${projectId}`);
}

export function createProject(api: Api, payload: ProjectCreatePayload): Promise<ProjectOut> {
  return api.post<ProjectOut>("/projects", payload);
}

export function updateProject(api: Api, projectId: string, patch: ProjectUpdatePayload): Promise<ProjectOut> {
  return api.patch<ProjectOut>(`/projects/${projectId}`, patch);
}
