# crm-lite-gateway

Spring Boot API Gateway in front of this repo's FastAPI backend (the parent
directory, `..`). The frontend should only ever call **this** gateway — it
never talks to the FastAPI backend directly.

This is a **stateless bearer-token pass-through** — no login endpoint, no
session, no SSO flow. It exists purely to:

- proxy `/api/v1/**` and `/health**` to the backend (`BACKEND_BASE_URL`)
- read the caller's `Authorization: Bearer <jwt>`, verify its HS256
  signature, and turn its `employee_id` / `roles` claims into the
  `X-Employee-Id` / `X-Roles` headers the backend trusts (see its
  `src/utils/security.py` and `.env.example`: *"Gateway ... forwards these
  headers; this service trusts them as-is"*)
- always strip any `X-Employee-Id` / `X-Roles` the caller sent itself first
  — the backend trusts those headers unconditionally, so letting a caller
  set them directly would be an impersonation hole
- handle CORS so the frontend never needs to

Whoever/whatever issues the JWT (your own login service, Entra ID, a
hand-minted test token) is entirely out of scope here — the gateway only
verifies the signature and forwards the claims. If a request has no token,
or an invalid one, it's forwarded with no identity headers (or rejected
with `401 INVALID_TOKEN` for a token that fails signature verification) —
the backend's own auth dependency is what turns "no identity" into a
401/403 for endpoints that require one.

## Expected JWT shape

HS256, signed with `JWT_SECRET`. Claims:

```json
{
  "employee_id": "fad3b90d-e6ae-4cd1-9be9-27b939cb0ec5",
  "roles": ["ADMIN"],
  "exp": 1755600000
}
```

- `employee_id` — the backend's employee UUID (`GET /api/v1/current-employee`
  looks this row up). Any value works for endpoints that don't require a
  linked employee row.
- `roles` — a JSON array (shown above) or a comma-separated string; either
  is accepted and forwarded as `X-Roles: ADMIN,SALES`.
- `exp` — standard JWT expiry; an expired token is rejected like any other
  invalid signature.

## Running locally

```
# 1. backend, from the repo root (one level up from this folder):
docker compose up -d && uv run alembic upgrade head && uv run uvicorn src.server:app --reload

# 2. this gateway, from this folder:
cp .env.example .env      # edit if needed
mvn spring-boot:run
```

## Testing with Postman / curl

1. Mint a test token (pure Python stdlib, no install needed):
   ```
   python scripts/mint_test_jwt.py --employee-id <an-employee-uuid-from-your-db> --roles ADMIN
   ```
   (Use a real employee UUID if you want `/api/v1/current-employee` to
   resolve a profile; any string works for endpoints that only check roles.)
2. In Postman, set header `Authorization: Bearer <token>` and call, e.g.:
   ```
   GET http://localhost:8080/api/v1/current-employee
   ```
3. Sanity checks worth trying:
   - No `Authorization` header at all → backend returns 401
     `UNAUTHENTICATED` (gateway forwarded with no identity headers).
   - A tampered/garbage token → gateway itself returns 401 `INVALID_TOKEN`
     (never reaches the backend).
   - Manually adding `X-Employee-Id`/`X-Roles` headers in Postman alongside
     a valid token → gateway overwrites them with the token's claims, so
     spoofing via those headers directly doesn't work.

## Config (env vars — see `.env.example`)

| Var | Default | Purpose |
|---|---|---|
| `BACKEND_BASE_URL` | `http://localhost:8000` | Where FastAPI is listening |
| `JWT_SECRET` | *(dev default in application.yml)* | HS256 secret used to verify the bearer token. **Change outside local dev.** |
| `GATEWAY_EMPLOYEE_HEADER` / `GATEWAY_ROLES_HEADER` | `X-Employee-Id` / `X-Roles` | Must match the backend's same-named settings |
| `GATEWAY_CORS_ORIGINS` | `http://localhost:3000` | Comma-separated browser origins allowed to call this gateway |
| `PORT` | `8080` | Gateway's own port |

## Notes / follow-ups

- No circuit breaker / rate limiting yet — add
  `spring-cloud-starter-circuitbreaker-reactor-resilience4j` if/when the
  backend's availability becomes a concern worth isolating.
- `/actuator/health` and `/actuator/gateway` are exposed for ops visibility.
- If you later want the gateway itself to issue tokens (a real login
  endpoint) rather than just verifying ones minted elsewhere, that's a
  separate addition — this scaffold deliberately doesn't include one.
