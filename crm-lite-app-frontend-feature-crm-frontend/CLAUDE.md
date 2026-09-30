# CLAUDE.md — working notes for this repo

## What this is
The Next.js frontend for Tachyon CLM / CRM Lite. This repo used to also host
the FastAPI backend directly, then briefly ran behind a Spring Boot API
gateway; there is no gateway anymore — this calls the FastAPI backend
directly (see `frontend/src/lib/api/client.ts` for the base URL config).
There is no backend code in this repo — only the UI.

## Ground rules
- All API calls go through `frontend/src/lib/api/client.ts`'s `useApi()` hook
  — never call `fetch` directly against the backend from a component.
- Real per-user auth, not a fixed token: `POST /auth/login` (email+password)
  returns a signed JWT, held in `lib/features/authSlice.ts` (persisted to
  localStorage by hand — see `lib/store.ts`'s `subscribe()`, there's no
  cookie/SSR auth in this app). `client.ts`'s `request()` reads the current
  token fresh from the store on every call and attaches it as
  `Authorization: Bearer <token>`; a 401 clears it, and `Shell.tsx` redirects
  to `/login` whenever there's no token (see its `mounted` guard — auth state
  only exists once the client has hydrated from localStorage, so the check
  waits for a real mount before redirecting on what might be a stale
  server-rendered "logged out" reading).
- The Topbar's "viewing as" role switcher (`src/lib/hooks`, `RoleOnly.tsx`,
  `identity.ts`) is a **separate, UI-only** RBAC simulation — it drives which
  capabilities/panels render locally, but does not change what identity the
  backend sees (that's the real logged-in employee's actual roles, from
  `authSlice`). Keep that distinction clear when touching role-gated UI —
  don't confuse the two.
- Errors from the backend come back as the uniform envelope
  `{"error": {code, message, request_id?}}`; `ApiError` in `client.ts` parses
  this — don't hand-roll a different error shape in a component.
- Per-module wire types live in `frontend/src/lib/api/<module>.ts` (crm,
  contracts, delivery, project, activity, admin, auth, identity, cadence) —
  mirroring what the API actually returns, not raw DB columns.

## Commands
Everything now runs from `frontend/`:
- Install: `cd frontend && npm install`
- Dev server: `cd frontend && npm run dev` (http://localhost:3000)
- Build: `cd frontend && npm run build && npm start`
- Lint: `cd frontend && npm run lint`

The backend (FastAPI) is a separate deployment — this repo only needs its
base URL, configured via `NEXT_PUBLIC_API_BASE_URL` in `frontend/.env.local`
(defaults to `http://localhost:8002/api/v1` for local dev). The backend also
needs `CORS_ORIGINS` set to wherever this frontend is actually served from —
there's no gateway to handle that anymore either.
