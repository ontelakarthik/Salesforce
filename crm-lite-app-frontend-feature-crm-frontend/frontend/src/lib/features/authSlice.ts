import { createSlice, type PayloadAction } from "@reduxjs/toolkit";

/** Mirrors the backend's CurrentEmployeeOut (see auth_models.py) — the
 * logged-in identity returned by POST /auth/login and GET /current-employee. */
export interface AuthEmployee {
  employee_id: string;
  email: string | null;
  full_name: string | null;
  roles: string[];
  is_active: boolean;
  access_state: string;
  permissions: string[];
}

export interface AuthState {
  token: string | null;
  employee: AuthEmployee | null;
  mustChangePassword: boolean;
}

const STORAGE_KEY = "crmlite.auth";

const emptyState: AuthState = { token: null, employee: null, mustChangePassword: false };

/** No SSR/cookie auth in this app — everything is client-side, so state is
 * persisted to localStorage by hand (see store.ts's subscribe() below) and
 * reloaded here at slice-init time. Guarded for the server-side render pass
 * (no `window`), which is a separate, throwaway module evaluation in
 * Next.js — the real browser evaluation that matters for an interactive
 * session always has `window`. */
/** Exported so roleSlice.ts can derive its own initial "viewing as" value
 * from the same restored session on a page reload — extraReducers only
 * fire when an action is actually dispatched, not when a slice's initial
 * state is loaded directly, so a returning user needs this too (not just
 * the loginSuccess case). */
export function loadPersistedAuth(): AuthState {
  if (typeof window === "undefined") return emptyState;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as AuthState) : emptyState;
  } catch {
    return emptyState;
  }
}

const authSlice = createSlice({
  name: "auth",
  initialState: loadPersistedAuth(),
  reducers: {
    loginSuccess(
      state,
      action: PayloadAction<{ token: string; employee: AuthEmployee; mustChangePassword: boolean }>
    ) {
      state.token = action.payload.token;
      state.employee = action.payload.employee;
      state.mustChangePassword = action.payload.mustChangePassword;
    },
    passwordChanged(state) {
      state.mustChangePassword = false;
    },
    logout(state) {
      state.token = null;
      state.employee = null;
      state.mustChangePassword = false;
    },
  },
});

export const { loginSuccess, passwordChanged, logout } = authSlice.actions;
export default authSlice.reducer;
