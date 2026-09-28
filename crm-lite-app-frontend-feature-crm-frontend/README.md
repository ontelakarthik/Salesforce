# Tachyon CLM — Frontend

The Next.js UI for Tachyon's Contract Lifecycle Management platform:
accounts → opportunities → agreements (NDA/MSA/SOW/etc.) → delivery
(budgets, rate cards, staffing, timesheets) → projects, plus cross-cutting
communications/notifications/audit logging and admin (employees/roles/teams).

The backend has been split out of this repo (FastAPI, separate deployment).
**There is no gateway anymore** — this app calls that FastAPI backend
directly. Auth is real per-user login: `POST /auth/login` (email + password)
returns a signed JWT, held client-side in Redux and persisted to
`localStorage` by hand (see `frontend/src/lib/features/authSlice.ts`);
`client.ts`'s `request()` reads it fresh on every call and attaches
`Authorization: Bearer <token>`. There is no fixed/shared bearer token and
no `NEXT_PUBLIC_API_BEARER_TOKEN` — every user authenticates with their own
credentials.

## Run

```bash
cd frontend
npm install
# create .env.local and set NEXT_PUBLIC_API_BASE_URL (no .env.example is
# checked in — see "Configuration" below for the value to use)
npm run dev                  # http://localhost:3000
# npm run build && npm start   # production build
```

## Configuration
- `NEXT_PUBLIC_API_BASE_URL` — the FastAPI backend's base URL, e.g.
  `http://localhost:8002/api/v1` for local dev (that's also the fallback
  used when the variable is unset — see `frontend/src/lib/api/client.ts`).
  For a deployed backend, use its real base URL (e.g. its Cloud Run URL,
  see the backend's README).

It's `NEXT_PUBLIC_*`, so it's inlined into the client bundle at build time —
see `frontend/Dockerfile` for the containerized build equivalent
(`--build-arg NEXT_PUBLIC_API_BASE_URL=...`) and `frontend/cloudbuild.yaml`
for the actual Cloud Build config that builds and pushes the deployed image
to Artifact Registry with that build arg set to the real backend URL.

## Layout
- `frontend/src/lib/api/client.ts` — the `useApi()` hook every component uses
  to call the backend; owns the base URL, auth header, and error envelope
  parsing (`ApiError`).
- `frontend/src/lib/api/<module>.ts` — wire types + helpers per module (crm,
  contracts, delivery, project, activity, admin, identity, cadence).
- `frontend/src/components/clm/` — pages and shared UI (Shell, Topbar, Rail,
  Panel, `RoleOnly` for capability-gated rendering).

## RBAC in the UI
The Topbar's "viewing as" role switcher only changes which capabilities and
panels render locally (`RoleOnly.tsx`) — it's a **separate, UI-only**
simulation, not real auth. Every request still carries the actual logged-in
employee's own JWT (from `POST /auth/login`) regardless of the selected
role — switching "viewing as" never changes what identity the backend sees.
