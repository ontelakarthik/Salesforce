import type { Api } from "./client";

/** Mirrors the backend's CurrentEmployeeOut (auth_models.py). */
export interface EmployeeInfo {
  employee_id: string;
  email: string | null;
  full_name: string | null;
  roles: string[];
  is_active: boolean;
  access_state: string;
  default_landing: string;
  permissions: string[];
}

export interface LoginPayload {
  email: string;
  password: string;
}

export interface LoginOut {
  access_token: string;
  token_type: string;
  must_change_password: boolean;
  employee: EmployeeInfo;
}

export interface ChangePasswordPayload {
  current_password: string;
  new_password: string;
}

export interface SetupAdminPayload {
  email: string;
  full_name: string;
}

export interface SetupAdminOut {
  email: string;
  password_email_sent: boolean;
  /** Only ever populated when password_email_sent is false — the one-time
   * guard means a failed email would otherwise permanently lock the
   * account out, so the backend surfaces it here as a last resort. */
  temp_password: string | null;
}

export function login(api: Api, payload: LoginPayload): Promise<LoginOut> {
  return api.post<LoginOut>("/auth/login", payload);
}

export function changePassword(api: Api, payload: ChangePasswordPayload): Promise<void> {
  return api.post<void>("/auth/change-password", payload);
}

/** POST /auth/setup-admin — only ever succeeds once, when no employee
 * exists yet anywhere (see auth_service.setup_admin() on the backend).
 * Every call after the first 409s permanently; this is not a general
 * sign-up endpoint. Same shape as adding any other employee: a temp
 * password is emailed, not set directly here — sign in with it afterward
 * at /login. */
export function setupAdmin(api: Api, payload: SetupAdminPayload): Promise<SetupAdminOut> {
  return api.post<SetupAdminOut>("/auth/setup-admin", payload);
}
