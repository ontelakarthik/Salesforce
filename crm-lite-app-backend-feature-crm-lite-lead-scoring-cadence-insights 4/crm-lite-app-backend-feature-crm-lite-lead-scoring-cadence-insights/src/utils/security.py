"""Authentication boundary — the backend verifies its own signed bearer
tokens (see POST /auth/login in auth_routes.py/auth_service.py). There is no
gateway in front translating a session into trusted headers anymore: a
caller either presents a valid `Authorization: Bearer <jwt>` (HS256, signed
with JWT_SECRET, claims `employee_id`/`profile_codes`/`capabilities`/`exp`)
or they don't, and DEV_AUTH_BYPASS is the only fallback for local dev
convenience — X-Employee-Id/X-Roles headers are never trusted directly,
since without a gateway there's nothing legitimate setting them (a caller
could otherwise just set "X-Roles: ADMIN" on any request and grant
themselves access).
"""
import base64
import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from fastapi import Header, HTTPException, Request, status

from src.config.config_reader import settings

_ALGORITHM = "HS256"


@dataclass
class CurrentUser:
    employee_id: str
    #: Which Profiles (see admin_models.Profile) this employee holds — kept
    #: mainly for display/audit labeling; enforcement uses `capabilities`.
    profile_codes: set[str] = field(default_factory=set)
    #: The union of every capability granted to any held profile — computed
    #: once at login (auth_service._capabilities_for(), DB-driven via the
    #: role_capability table) and baked into the JWT. This, not profile_codes,
    #: is what requires()/has_capability() check.
    capabilities: set[str] = field(default_factory=set)
    #: Memoization cache for subordinate_employee_ids() below — private, not
    #: part of equality/repr. A fresh CurrentUser is minted once per request
    #: (see get_current_user()), so caching here makes the role-hierarchy
    #: walk cost exactly one computation per request no matter how many
    #: scope checks reference it (list endpoints call it once per row).
    _subordinate_ids_cache: set[UUID] | None = field(
        default=None, repr=False, compare=False)

    def has_capability(self, key: str) -> bool:
        return key in self.capabilities

    def subordinate_employee_ids(self) -> set[UUID]:
        """Every employee holding a Profile strictly beneath any profile
        this caller holds, in the admin-configurable role hierarchy (see
        admin_models.Profile.parent_role_id) — i.e. who a manager's role
        hierarchy grants them visibility into, on top of their own rows.
        Deliberately excludes the caller's own held role(s): two employees
        holding the exact same profile are peers, not subordinates, and
        should NOT see each other's rows through this mechanism (that's what
        the records.see_all capability or explicit sharing would be for).

        Computed live (not baked into the JWT — reorganizing the hierarchy
        should take effect immediately) and memoized on this instance, since
        a fresh CurrentUser is minted per request."""
        if self._subordinate_ids_cache is not None:
            return self._subordinate_ids_cache
        from src.repositories.admin_repository import (
            get_employee_role_repository, get_profile_repository)
        profiles = get_profile_repository().list()
        held_ids = {p.id for p in profiles if p.code in self.profile_codes}
        children: dict[int, list[int]] = {}
        for p in profiles:
            if p.parent_role_id is not None:
                children.setdefault(p.parent_role_id, []).append(p.id)
        descendant_ids: set[int] = set()
        stack = list(held_ids)
        while stack:
            for child_id in children.get(stack.pop(), []):
                if child_id not in descendant_ids:
                    descendant_ids.add(child_id)
                    stack.append(child_id)
        result: set[UUID] = set()
        if descendant_ids:
            result = {r.employee_id for r in
                      get_employee_role_repository().list_for_roles(descendant_ids)}
        self._subordinate_ids_cache = result
        return result

    def employee_uuid(self) -> UUID | None:
        """CurrentUser.employee_id is the raw gateway-forwarded identity
        string; in a real deployment it's the employee's DB id (a UUID). The
        DEV_AUTH_BYPASS placeholder ("dev-admin") and any other non-UUID
        value simply resolve to None — callers that need a real employee FK
        (signing, approving, submitting) should treat None as "no linked
        employee record" rather than guessing."""
        try:
            return UUID(self.employee_id)
        except ValueError:
            return None


def _parse_str_set(raw, *, upper: bool) -> set[str]:
    """Accepts a JWT claim in either shape a token might carry it — a JSON
    list (the normal case) or a comma-separated string. `upper` uppercases
    profile codes (SALES, ADMIN, ...) but must stay False for capability
    keys, which are lowercase dotted strings (leads.write)."""
    if raw is None:
        parts: list[str] = []
    elif isinstance(raw, list):
        parts = [str(p) for p in raw]
    else:
        parts = str(raw).split(",")
    out: set[str] = set()
    for part in parts:
        part = part.strip()
        if not part:
            continue
        out.add(part.upper() if upper else part)
    return out


def _dev_bypass_user() -> CurrentUser:
    # Local import to avoid a security.py <-> permissions.py circular import
    # (permissions.py imports CurrentUser/get_current_user from this module).
    from src.utils.permissions import CAPABILITY_REGISTRY
    return CurrentUser(employee_id="dev-admin", profile_codes={"ADMIN"},
                       capabilities=set(CAPABILITY_REGISTRY.keys()))


def mint_access_token(employee_id: str, profile_codes: set[str], capabilities: set[str]) -> str:
    """Signs the JWT a client should send back as `Authorization: Bearer
    <token>` on every subsequent request — see POST /auth/login. Prefer
    auth_service.mint_token_for_profiles() over calling this directly: it
    resolves `capabilities` from the DB for you, the same way real login
    does, so a caller can't accidentally mint a token whose capabilities
    claim doesn't match what its profile_codes are actually granted."""
    now = datetime.now(timezone.utc)
    payload = {
        "employee_id": employee_id,
        "profile_codes": sorted(profile_codes),
        "capabilities": sorted(capabilities),
        "iat": now,
        "exp": now + timedelta(hours=settings.JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=_ALGORITHM)


def _resolve_bearer(authorization: str | None) -> CurrentUser | None:
    """None means "no token presented" (caller decides what that means —
    DEV_AUTH_BYPASS or 401); an invalid/expired token raises 401 directly,
    since presenting a bad token is different from presenting none at all.

    A token missing the `capabilities`/`profile_codes` claims entirely (not
    merely empty — a legitimately zero-capability profile has an empty list,
    which is fine) is from before this claim shape existed and is rejected
    the same way: there's no session store/blacklist anywhere in this
    codebase to force revocation another way, and maintaining two parallel
    enforcement engines (old `roles`-claim + static dict, new DB-driven
    capabilities) even temporarily isn't worth it for a bounded, ≤
    JWT_EXPIRY_HOURS-long window — this just asks that caller to log in
    again, once, instead of failing confusingly capability-by-capability."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[len("Bearer "):]
    try:
        claims = jwt.decode(token, settings.JWT_SECRET, algorithms=[_ALGORITHM])
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
            {"code": "INVALID_TOKEN",
             "message": "The bearer token is missing required claims, malformed, expired, "
                        "or has an invalid signature."}) from exc
    employee_id = claims.get("employee_id")
    if not employee_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
            {"code": "INVALID_TOKEN", "message": "Token is missing an employee_id claim."})
    if "capabilities" not in claims or "profile_codes" not in claims:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
            {"code": "TOKEN_STALE_FORMAT",
             "message": "Your session is from a previous version of this app. Please log in again."})
    return CurrentUser(
        employee_id=str(employee_id),
        profile_codes=_parse_str_set(claims.get("profile_codes"), upper=True),
        capabilities=_parse_str_set(claims.get("capabilities"), upper=False),
    )


def get_current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> CurrentUser:
    """Require an authenticated employee WITH at least one profile."""
    user = _resolve_bearer(authorization)
    if user is not None:
        if not user.profile_codes:  # NO_ROLE holding state
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                {"code": "FORBIDDEN", "message": "Access not set up. Contact an administrator."})
        return user
    if settings.DEV_AUTH_BYPASS:
        return _dev_bypass_user()
    raise HTTPException(status.HTTP_401_UNAUTHORIZED,
        {"code": "UNAUTHENTICATED", "message": "Missing or invalid bearer token."})


def get_identity(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> CurrentUser:
    """Authenticated employee, profiles optional (used by /current-employee)."""
    user = _resolve_bearer(authorization)
    if user is not None:
        return user
    if settings.DEV_AUTH_BYPASS:
        return _dev_bypass_user()
    raise HTTPException(status.HTTP_401_UNAUTHORIZED,
        {"code": "UNAUTHENTICATED", "message": "Missing or invalid bearer token."})


_PROD_ENVS = {"prod", "production"}


def require_gateway_callback(
    x_gateway_secret: str | None = Header(default=None, alias="X-Gateway-Secret"),
) -> None:
    """Guards `/auth/callback`.

    That endpoint resolves identity from caller-supplied query params
    (entra_object_id/email/full_name) rather than gateway-trusted headers,
    because there's no employee session yet at first login — unlike every
    other route, it can't lean on X-Employee-Id/X-Roles for provenance. In
    production this closes that gap by requiring a shared secret only the
    gateway holds; outside production (local/dev, and the test suite, which
    documents itself as simulating what the gateway would forward) this is a
    no-op so the existing dev workflow is unchanged.
    """
    if settings.APP_ENV.strip().lower() not in _PROD_ENVS:
        return
    if not settings.GATEWAY_CALLBACK_SECRET or x_gateway_secret != settings.GATEWAY_CALLBACK_SECRET:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
            {"code": "UNAUTHENTICATED", "message": "Missing or invalid gateway credential."})


def require_email_intake_secret(
    x_email_intake_secret: str | None = Header(default=None, alias="X-Email-Intake-Secret"),
) -> None:
    """Guards POST /email-intake/poll. That caller is a scheduler (Cloud
    Scheduler in the real deployment), not a logged-in employee, so there's
    no bearer token to check — a shared secret is the only option. Unlike
    require_gateway_callback() this is enforced in every environment, not
    just prod: every successful call creates real Lead/Communication rows,
    so leaving it open in local/dev would let anyone with network access to
    this service create data."""
    if not settings.EMAIL_INTAKE_SECRET or x_email_intake_secret != settings.EMAIL_INTAKE_SECRET:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
            {"code": "UNAUTHENTICATED", "message": "Missing or invalid email-intake credential."})


def require_cadence_scheduler_secret(
    x_cadence_scheduler_secret: str | None = Header(default=None, alias="X-Cadence-Scheduler-Secret"),
) -> None:
    """Guards POST /cadence/advance-due-steps. Same shape as
    require_email_intake_secret above — that caller is a scheduler (Cloud
    Scheduler in the real deployment), not a logged-in employee, so there's
    no bearer token to check. Enforced in every environment, not just prod:
    every successful call auto-resolves real cadence tasks and advances
    real enrollments, so leaving it open in local/dev would let anyone with
    network access to this service mutate cadence state."""
    if (not settings.CADENCE_SCHEDULER_SECRET
            or x_cadence_scheduler_secret != settings.CADENCE_SCHEDULER_SECRET):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
            {"code": "UNAUTHENTICATED", "message": "Missing or invalid cadence-scheduler credential."})


def _twilio_signature(url: str, params: dict[str, str], auth_token: str) -> str:
    """https://www.twilio.com/docs/usage/security#validating-requests — HMAC-
    SHA1 over the exact request URL with every POST param, sorted by key,
    appended as `key` immediately followed by `value` (no delimiters),
    keyed on the account's own Auth Token, base64-encoded."""
    data = url + "".join(f"{key}{params[key]}" for key in sorted(params))
    digest = hmac.new(auth_token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


async def require_twilio_signature(
    request: Request,
    x_twilio_signature: str | None = Header(default=None, alias="X-Twilio-Signature"),
) -> dict[str, str]:
    """Guards POST /sms-intake/webhook. Unlike require_email_intake_secret/
    require_cadence_scheduler_secret above, the caller (Twilio) doesn't
    present a shared secret we chose ourselves — it signs every webhook
    request itself, using OUR OWN TWILIO_AUTH_TOKEN as the HMAC key over the
    request URL plus its form params (see _twilio_signature above), so
    verifying that signature doubles as proof this call really came from
    Twilio and wasn't replayed or tampered with. Enforced in every
    environment (not just prod), same reasoning as the other two: every
    valid call can create a real Communication.

    Returns the parsed form fields so crm_routes.py's route handler doesn't
    need to read the request body a second time (Starlette caches the
    stream after the first .form() read, but there's no reason to parse it
    twice).

    Cloud Run note: behind the gateway, `request.url` reflects whatever
    scheme/host Spring Cloud Gateway's own outbound hop used — not
    necessarily the `https://<public host>` URL Twilio actually signed (the
    gateway has no `server.forward-headers-strategy: framework`, so it
    can't be trusted to relay Cloud Run's `X-Forwarded-Proto` onward).
    Same "internal http:// URL Twilio never signed" problem
    require_twilio_whatsapp_signature below was hardened against — this
    reuses that fix: when TWILIO_PUBLIC_BASE_URL is set, the signed URL is
    reconstructed from it (scheme+host) plus this request's own path/query,
    rather than trusting request.url directly. Falls back to request.url
    when unset (e.g. local dev without a gateway in front), where
    Dockerfile's `--proxy-headers` on uvicorn is enough on its own.
    """
    if not settings.TWILIO_AUTH_TOKEN:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
            {"code": "UNAUTHENTICATED", "message": "TWILIO_AUTH_TOKEN is not configured."})
    if not x_twilio_signature:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
            {"code": "UNAUTHENTICATED", "message": "Missing X-Twilio-Signature header."})

    form = await request.form()
    params = {key: str(value) for key, value in form.items()}
    if settings.TWILIO_PUBLIC_BASE_URL:
        url = settings.TWILIO_PUBLIC_BASE_URL.rstrip("/") + request.url.path
        if request.url.query:
            url += f"?{request.url.query}"
    else:
        url = str(request.url)
    expected = _twilio_signature(url, params, settings.TWILIO_AUTH_TOKEN)
    if not hmac.compare_digest(expected, x_twilio_signature):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
            {"code": "UNAUTHENTICATED", "message": "Invalid Twilio signature."})
    return params


async def require_twilio_whatsapp_signature(
    request: Request,
    x_twilio_signature: str | None = Header(default=None, alias="X-Twilio-Signature"),
) -> dict[str, str]:
    """Guards POST /whatsapp/webhook/inbound and /whatsapp/webhook/status.

    Reuses _twilio_signature() above (the same Twilio request-signing HMAC
    require_twilio_signature already verifies for SMS) rather than
    duplicating it, but is its own function — not just a reuse of
    require_twilio_signature — because the WhatsApp feature needs two
    things that one doesn't have: (1) a WHATSAPP_WEBHOOK_ENABLED kill
    switch; (2) (per this feature's own hardening requirement)
    reconstructing the signed URL from TWILIO_PUBLIC_BASE_URL rather than
    trusting request.url directly, since behind a proxy that could resolve
    to an internal http:// URL Twilio never actually signed. Also answers
    403 (not require_twilio_signature's 401) on an invalid/missing
    signature. Signs against the same TWILIO_AUTH_TOKEN as SMS — SMS,
    WhatsApp and Voice all share one Twilio account by this deployment's
    choice (see integrations/twilio_whatsapp.py).

    Returns the parsed form fields, same as require_twilio_signature, so
    the route handler doesn't read the request body a second time.
    """
    if not settings.WHATSAPP_WEBHOOK_ENABLED:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
            {"code": "WHATSAPP_NOT_CONFIGURED", "message": "WhatsApp webhook processing is disabled."})
    if not settings.TWILIO_AUTH_TOKEN:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
            {"code": "FORBIDDEN", "message": "TWILIO_AUTH_TOKEN is not configured."})
    if not x_twilio_signature:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
            {"code": "FORBIDDEN", "message": "Missing X-Twilio-Signature header."})

    form = await request.form()
    params = {key: str(value) for key, value in form.items()}
    if settings.TWILIO_PUBLIC_BASE_URL:
        url = settings.TWILIO_PUBLIC_BASE_URL.rstrip("/") + request.url.path
        if request.url.query:
            url += f"?{request.url.query}"
    else:
        url = str(request.url)
    expected = _twilio_signature(url, params, settings.TWILIO_AUTH_TOKEN)
    if not hmac.compare_digest(expected, x_twilio_signature):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
            {"code": "FORBIDDEN", "message": "Invalid Twilio signature."})
    return params


async def require_twilio_voice_signature(
    request: Request,
    x_twilio_signature: str | None = Header(default=None, alias="X-Twilio-Signature"),
) -> dict[str, str]:
    """Guards POST /voice/webhook/connect and /voice/webhook/status.

    Same shape as require_twilio_whatsapp_signature (reuses
    _twilio_signature(), reconstructs the signed URL from a configured
    public base URL, answers 403 on an invalid/missing signature) but keyed
    on TWILIO_VOICE_PUBLIC_BASE_URL — the voice webhooks are a separate
    TwiML App/URL from the WhatsApp ones, but sign with the same shared
    TWILIO_AUTH_TOKEN, since SMS/WhatsApp/Voice are all one Twilio account
    by this deployment's choice.
    """
    if not settings.TWILIO_AUTH_TOKEN:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
            {"code": "FORBIDDEN", "message": "TWILIO_AUTH_TOKEN is not configured."})
    if not x_twilio_signature:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
            {"code": "FORBIDDEN", "message": "Missing X-Twilio-Signature header."})

    form = await request.form()
    params = {key: str(value) for key, value in form.items()}
    if settings.TWILIO_VOICE_PUBLIC_BASE_URL:
        url = settings.TWILIO_VOICE_PUBLIC_BASE_URL.rstrip("/") + request.url.path
        if request.url.query:
            url += f"?{request.url.query}"
    else:
        url = str(request.url)
    expected = _twilio_signature(url, params, settings.TWILIO_AUTH_TOKEN)
    if not hmac.compare_digest(expected, x_twilio_signature):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
            {"code": "FORBIDDEN", "message": "Invalid Twilio signature."})
    return params
