"use client";

import { useCallback, useMemo } from "react";
import { logout } from "@/lib/features/authSlice";
import { useAppSelector } from "@/lib/hooks";
import { store } from "@/lib/store";

// No gateway in front anymore — the backend verifies its own signed bearer
// tokens directly (see POST /auth/login). This now points straight at the
// FastAPI service, not a gateway.
const BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8002/api/v1").replace(/\/$/, "");

export interface ApiFieldError {
  loc: (string | number)[];
  msg: string;
  type: string;
}

/** Mirrors the gateway/backend's uniform error envelope: {"error": {code, message, fields?}}. */
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public fields?: ApiFieldError[]
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Query = Record<string, unknown>;

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  query?: Query;
}

function buildUrl(path: string, query?: Query): string {
  const url = new URL(BASE_URL + path);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  // Read fresh on every call (not captured at module load) so a login that
  // happens after this module first evaluates is picked up immediately —
  // no token yet (e.g. the login request itself) just omits the header,
  // which is exactly what an unauthenticated POST /auth/login needs.
  const token = store.getState().auth.token;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(buildUrl(path, options.query), {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  if (res.status === 204) return undefined as T;

  const payload = await res.json().catch(() => null);

  if (!res.ok) {
    const err = payload?.error ?? {};
    // A previously-valid token expired or was invalidated — clear it so
    // Shell's auth guard redirects to /login instead of the app silently
    // re-sending a dead token on every subsequent request.
    if (res.status === 401 && token) store.dispatch(logout());
    throw new ApiError(res.status, err.code ?? "UNKNOWN_ERROR", err.message ?? res.statusText, err.fields);
  }

  return payload as T;
}

/**
 * Bound fetch helpers. Every request carries the real per-user bearer token
 * from POST /auth/login (see `./auth` and `lib/features/authSlice.ts`), read
 * fresh from the store on each call — nothing here is a fixed/shared token
 * anymore. `role` is still returned for the separate "viewing as" UI-only
 * RBAC simulation (see `./identity`) — it is never sent as a request header.
 */
export function useApi() {
  const role = useAppSelector((s) => s.role.value);

  const get = useCallback(
    <T,>(path: string, query?: Query) => request<T>(path, { method: "GET", query }),
    []
  );
  const post = useCallback(
    <T,>(path: string, body?: unknown) => request<T>(path, { method: "POST", body }),
    []
  );
  const patch = useCallback(
    <T,>(path: string, body?: unknown) => request<T>(path, { method: "PATCH", body }),
    []
  );
  const put = useCallback(
    <T,>(path: string, body?: unknown) => request<T>(path, { method: "PUT", body }),
    []
  );
  const del = useCallback((path: string) => request<void>(path, { method: "DELETE" }), []);

  // Memoized so an `[api]` effect dependency doesn't refire every render —
  // without this, useApi() returns a fresh object identity each call even
  // though get/post/patch/put/del are individually stable.
  return useMemo(() => ({ role, get, post, patch, put, del }), [role, get, post, patch, put, del]);
}

export type Api = ReturnType<typeof useApi>;

/**
 * Wraps one fetch so a caller combining several independent, separately-
 * permissioned requests (a dashboard's stat cards, say) can tell "this
 * profile just isn't allowed to see this one" apart from a real failure,
 * without a bare Promise.all letting one 403 wipe out every other request
 * that actually succeeded. A profile lacking permission should have that
 * one piece quietly show as empty — not a raw backend error on the page.
 */
export type Graceful<T> =
  | { ok: true; value: T }
  | { ok: false; forbidden: true }
  | { ok: false; forbidden: false; message: string };

export async function fetchGraceful<T>(promise: Promise<T>): Promise<Graceful<T>> {
  try {
    return { ok: true, value: await promise };
  } catch (err) {
    if (err instanceof ApiError && err.code === "FORBIDDEN") return { ok: false, forbidden: true };
    return { ok: false, forbidden: false, message: err instanceof ApiError ? err.message : "Failed to load." };
  }
}
