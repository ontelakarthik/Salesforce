# CRM Lite — Backend

FastAPI business services backing the CRM Lite app (and the wider Tachyon
Connect platform, which shares this same database/schema — see "Scope"
below). Current focus is CRM Lite: Leads (with rule-based Lead Scoring and
a Country/State-Province/Region geography — USA and Canada only, Region
always derived from Country + State/Province, never stored; see
`src/utils/geo.py`), Campaigns, Accounts/Contacts/Opportunities, the Sales
Cadence engine
(including BREAK/FOLLOW_UP steps, business-day wait times, and a
scheduler-driven `POST /cadence/advance-due-steps` that auto-resolves due
BREAKs and auto-skips FOLLOW_UPs the lead has already replied to), Lead
Email/Call Insights (with admin-configurable call dispositions and
open/reply tracking), a Sales Lead/Manager team-activity dashboard,
AI-assisted email drafting + call prep (Cohere) with real SMTP send, and
Salesforce-style record-level access control — Organization-Wide Defaults,
Role Hierarchy, user-based Record Sharing, and Sales Territory/Region
assignment — for Lead/Account/Contact/Opportunity/Campaign (see "Record
access control" below).

## Stack

FastAPI + SQLAlchemy 2.0 + Alembic, Postgres only. Layered architecture:
`src/server` (routes) → `src/services` → `src/repositories` → `src/models`
(ORM + Pydantic schemas together, no separate `schemas/` package). Enforced
by `tests/test_layering.py`.

## Scope

This service owns every table in the platform's schema, grouped by module
(`crm`, `contracts`, `delivery`, `project`, `activity`, `admin`, `auth`,
`platform`) — not just CRM Lite's. CRM Lite's Lead→Convert flow produces
Account/Contact/Opportunity rows that the same schema's Agreement/Project/
SOW tables reference, so the modules aren't separable into different
services without breaking those foreign keys. Active feature work right now
is scoped to the `crm` module (Leads, Campaigns, Lead Scoring, Sales
Cadence, Email/Call Insights); the other modules exist, are fully
implemented, and are shared with the CLM app.

## Record access control

Lead/Account/Contact/Opportunity/Campaign are governed by one centralized
decision point, `src/services/record_access_service.py::can_user_access_record()`
(delegated to from `crm_service.py`'s `_in_read/write/delete_scope()` and
every relevant route). Precedence, first match wins:

1. `records.see_all` capability — full access to everything.
2. Record ownership (direct, or for CONTACT, derived from its parent
   Account's owner) — full access; DELETE is still separately gated by the
   object's own delete capability at the route layer.
3. **Role Hierarchy** — a manager (per the admin-configurable Profile tree,
   `PATCH /admin/profiles/{id}` → `parent_role_id`) gets the same READ/EDIT
   a subordinate's ownership would, but never DELETE. Two employees holding
   the *same* profile are peers, not manager/subordinate, and get nothing
   from this layer.
4. **Organization-Wide Default** (`GET/PUT /admin/org-wide-defaults`) —
   PRIVATE (the default) means owner/manager/share only; PUBLIC_READ_ONLY
   opens reads to everyone; PUBLIC_READ_WRITE opens both.
5. An explicit **Record Share** (`/record-shares`) — grants exactly READ or
   EDIT, never DELETE, and only ever adds access on top of the above.

**Sales Territory/Region** (`admin_models.Territory` — an admin-managed
lookup, seeded with `USA`/`CANADA` via `/admin/lookups/territory`, same
generic CRUD every other lookup table uses) is deliberately **not** part of
this precedence chain. `Employee.territory_id` is part of an employee's
assignment data; a new Account/Lead simply defaults its own `territory_id`
from its resolved owner's territory at create time (never recomputed
afterward) — it is data and a defaulting convenience only. Two employees
sharing a territory do **not** automatically see each other's PRIVATE
records; only the layers above grant that. This is also fully independent
of Billing Country/State (`src/utils/geo.py`) — never auto-equated with it.

See `tests/test_record_access.py` and `tests/test_territory_and_hierarchy.py`
for the full behavioral spec as executable tests.

## Configuration

Copy `.env.example` to `.env` and fill in real values for your environment.
Every setting is read from the environment at startup (`src/config/
config.py`) — nothing is hardcoded in source:

- `DATABASE_URL` has **no default** — a missing value fails startup loudly
  rather than silently falling back to something local.
- **No gateway in front anymore** — this service verifies its own signed
  bearer tokens directly. `JWT_SECRET` has **no default** (required in every
  environment); `POST /auth/login` mints tokens, and every other endpoint's
  identity comes from decoding the `Authorization: Bearer <jwt>` header
  itself (see `src/utils/security.py`). `JWT_EXPIRY_HOURS` defaults to `12`.
- `DEV_AUTH_BYPASS` defaults to `false` (secure by default). Only set it to
  `true` in local development — never in a shared/staging/production
  environment, since it grants ADMIN to any request with no bearer token.
- `CORS_ORIGINS` (list, defaults to `["http://localhost:3000"]`) — the
  browser origins allowed to call this API. The backend owns CORS directly
  now (no gateway in front to set `Access-Control-*` headers), so this must
  be set to wherever the frontend is actually served from.
- `GATEWAY_CALLBACK_SECRET` is a **dormant legacy scaffold** for
  `GET /auth/callback` (Entra SSO fronted by a gateway) — not on the real
  `POST /auth/login` path users hit today. No default; leave unset unless
  gateway-fronted SSO is wired up again later.
- `COHERE_API_KEY` and `SMTP_HOST`/`SMTP_FROM_ADDRESS` are optional — unset,
  the AI-drafting and email-sending endpoints just return a clear 503
  ("not configured") instead of failing startup. Both are validated at
  call-time, not at process boot, since not every deployment needs them.
- `TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN`/`TWILIO_FROM_NUMBER` are optional,
  same treatment as the SMTP settings above — unset, `POST
  /leads/{lead_id}/sms` (the SMS action on a Lead's Cadence Activity tab)
  just returns a clear 503 ("not configured") instead of failing startup.
  Validated at call-time (`src/services/sms_service.py::get_sms_sender()`),
  not at process boot. Get real values from the Twilio Console.
  `TWILIO_AUTH_TOKEN` is also reused to verify inbound webhook calls to
  `POST /sms-intake/webhook` (see "Inbound SMS-to-lead" below) — there's no
  separate secret to configure for that endpoint.

## Inbound SMS-to-lead

`POST /sms-intake/webhook` is Twilio's own webhook target, not a scheduler
tick and not a logged-in employee's request — Twilio calls it directly the
moment a reply arrives at `TWILIO_FROM_NUMBER`, and every call is
authenticated by verifying Twilio's `X-Twilio-Signature` header (HMAC-SHA1
over the request URL + form params, keyed on `TWILIO_AUTH_TOKEN` — see
`src/utils/security.py::require_twilio_signature()`), not a shared secret we
chose ourselves like `EMAIL_INTAKE_SECRET`/`CADENCE_SCHEDULER_SECRET`.

To receive replies: in the Twilio Console, open that phone number's config
(**Phone Numbers → Manage → Active Numbers → *the number* → Messaging**) and
set **"A MESSAGE COMES IN"** to `POST` your deployed API's
`/api/v1/sms-intake/webhook` URL. The `Dockerfile`'s `uvicorn` invocation
runs with `--proxy-headers` so it trusts Cloud Run's forwarded-proto header
— without that, the URL Starlette sees (and signs against) would read
`http` instead of the `https` URL Twilio actually signed, and every real
webhook call would fail verification.

The sender's number is matched against `Lead.contact_phone`, then
`Lead.mobile_phone` (`LeadRepository.find_by_phone()`), and logged as an
`INBOUND`/`SMS` Communication on a match. **Unlike inbound email**, a reply
from a number that matches no Lead does **not** auto-create one:
`Lead.contact_email` is required (`NOT NULL`) and an SMS reply carries no
email address to satisfy it, so that case is simply not logged against any
record — `matched_lead: false` in the response is the signal that a Lead
with that number needs to be created by hand first. Twilio's own retries of
the same webhook call (identified by `MessageSid`) are deduplicated the same
way inbound email dedupes on `graph_message_id`.
- `EMAIL_INTAKE_SECRET` has no default — required in **every** environment.
  `POST /email-intake/poll` (a scheduler tick, not a person) checks it and
  401s without it — every successful call creates real Lead/Communication
  rows from a dedicated inbox.
- `CADENCE_SCHEDULER_SECRET` has no default — required in **every**
  environment (not just prod), same treatment as `EMAIL_INTAKE_SECRET`.
  `POST /cadence/advance-due-steps` (the Sales Cadence scheduler tick, meant
  to be hit on a schedule rather than by a person) checks it via the
  `X-Cadence-Scheduler-Secret` header and 401s without it — every successful
  call auto-resolves real cadence tasks and advances real enrollments.

## Local development

There is no gateway in front of this service anymore — it's the
browser-facing entry point directly (owns its own CORS and verifies its own
JWTs; see "Configuration" above). The `gateway/` folder and its service in
`docker-compose.yml` are a legacy Spring Boot scaffold kept around in case a
gateway-fronted SSO flow is reintroduced later — not part of the active
deployment path, and a frontend should call this backend directly instead.

`docker-compose.yml` defines Postgres + this backend — `docker compose up -d`
builds and runs both, migrations included. For iterating on backend code
with a fast reload loop, run just Postgres in Docker and the API on the
host instead:

```
docker compose up -d postgres                 # Postgres on localhost:5434
cp .env.example .env                          # then edit as needed
uv sync
uv run alembic upgrade head
uv run uvicorn src.server:app --reload
```

API docs at `http://127.0.0.1:8000/docs`. Health check at `/health`.

## Tests

```
uv run pytest -q
```

Runs against a real Postgres instance (no mocking) — `docker compose up -d`
must be running first. `tests/conftest.py` sets `DEV_AUTH_BYPASS=true` for
the test session only.

## Migrations

```
uv run alembic revision --autogenerate -m "..."
uv run alembic upgrade head
```

Autogenerate is safe for pure additions (new tables/columns) but does
**not** detect `CheckConstraint` changes or produce correct DDL for
renames — those need hand-written `op.*` calls. Always verify a new
migration round-trips cleanly (`upgrade head` → `downgrade -1` → `upgrade
head`) and that a follow-up `alembic revision --autogenerate` produces an
empty diff before committing it.

## Production

`Dockerfile` builds a container image with no secrets baked in — every
value comes from the runtime environment (container env vars / your
platform's secret store). `docker-compose.yml` runs it locally for
development/testing only; a real deployment builds and runs this image
through its own orchestration, not this compose file (and does **not**
need the `gateway/` image — see "Local development" above).

Deployed today as a container on **Google Cloud Run** (its public URL is
what the frontend's `NEXT_PUBLIC_API_BASE_URL` points at — see the
frontend's `cloudbuild.yaml` and its README). Set `CORS_ORIGINS` to the
frontend's real deployed origin, and `JWT_SECRET`/`EMAIL_INTAKE_SECRET`/
`CADENCE_SCHEDULER_SECRET` to real generated values (never the `.env.example`
placeholders) via Cloud Run's own env var / Secret Manager config.
