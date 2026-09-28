"""Typed application settings. Skeleton — values loaded via config_reader."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- service meta ---
    APP_NAME: str = "crm-lite-service"
    APP_ENV: str = "local"           # local | dev | prod
    API_PREFIX: str = "/api/v1"
    LOG_LEVEL: str = "INFO"

    # --- persistence: Postgres only (see docker-compose.yml for local dev;
    # Azure Database for PostgreSQL in real environments — same URL scheme,
    # different host/credentials, no code change) ---
    # No default on purpose: credentials must never be hardcoded in source.
    # This is sourced only from .env (see .env.example) via config_reader; a
    # missing value fails startup loudly instead of silently using a fallback.
    DATABASE_URL: str

    # --- auth: the backend verifies its own bearer tokens now (no gateway in
    # front — see POST /auth/login in auth_routes.py). No default on purpose,
    # same treatment as DATABASE_URL: every request's identity depends on
    # this, so a deployment that forgets to set it must fail loudly at
    # startup, never fall back to a guessable value.
    JWT_SECRET: str
    JWT_EXPIRY_HOURS: int = 12
    # Secure by default: a deployment that forgets to set this explicitly
    # must NOT silently grant ADMIN to unauthenticated callers. Local/dev
    # workflows (and the test suite, via tests/conftest.py) opt in explicitly
    # via DEV_AUTH_BYPASS=true rather than relying on this default.
    DEV_AUTH_BYPASS: bool = False     # inject fake ADMIN when no bearer token given (dev only)

    # --- CORS: origins allowed to call this API directly from the browser.
    # The backend owns this itself now — no gateway in front to set
    # Access-Control-* headers (see src/server/__init__.py). ---
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # --- legacy Entra SSO scaffold (src/server/auth_routes.py's /auth/callback) ---
    # Dormant now that there's no gateway to front an SSO redirect — kept in
    # case Entra SSO is wired up again later, not on the POST /auth/login
    # path real users hit today. No default: never hardcode a shared secret.
    GATEWAY_CALLBACK_SECRET: str | None = None

    # --- AI email/call drafting (src/services/llm_client.py) ---
    # Optional, unlike DATABASE_URL: not every deployment needs this feature,
    # so a missing key doesn't fail startup — it fails the one request that
    # needs it, with a clear 503 (see llm_client.get_llm_client()). Cohere is
    # the current provider (free tier); the client is a small Protocol so
    # swapping providers later doesn't touch any calling code.
    COHERE_API_KEY: str | None = None
    # "command-r" (the un-dated alias) was retired by Cohere on 2025-09-15;
    # pin to a dated snapshot so this doesn't silently break again when the
    # alias moves.
    COHERE_MODEL: str = "command-r-08-2024"

    # --- Outbound email sending (src/services/email_client.py) ---
    # Same "optional, validated at call-time" treatment as the AI settings
    # above — SMTP relay works with almost any provider (O365, Gmail
    # Workspace, SendGrid's SMTP endpoint, ...) via these five values alone.
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM_ADDRESS: str | None = None

    # --- Outbound SMS sending (src/services/sms_service.py) — the SMS channel
    # on a Lead's Cadence Activity tab, a third Communication channel
    # alongside logged calls and sent emails. Same "optional, validated at
    # call-time" treatment as the SMTP settings above: not every deployment
    # sends SMS, so a missing value doesn't fail startup — it fails the one
    # request that needs it, with a clear 503 (see sms_service.get_sms_sender()).
    TWILIO_ACCOUNT_SID: str | None = None
    TWILIO_AUTH_TOKEN: str | None = None
    TWILIO_FROM_NUMBER: str | None = None

    # --- Outbound WhatsApp sending (src/integrations/twilio_whatsapp.py) —
    # a fourth Communication channel, same "optional, validated at
    # call-time" treatment as TWILIO_FROM_NUMBER above. Shares
    # TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN above (one Twilio account for
    # SMS, WhatsApp and Voice, by this deployment's choice) — only the
    # sender identity differs, since a WhatsApp-enabled number is a
    # distinct resource from the SMS one (e.g. the Sandbox number during
    # development).
    TWILIO_WHATSAPP_FROM: str | None = None
    # This service's own publicly-reachable base URL (e.g. an ngrok URL in
    # dev, the real Cloud Run URL in prod) — used only to reconstruct the
    # exact URL Twilio signed when verifying X-Twilio-Signature on the
    # WhatsApp webhooks (see utils.security.require_twilio_whatsapp_signature),
    # since request.url alone isn't trustworthy behind a proxy. No default:
    # never guess a production URL. If unset, webhook signature verification
    # falls back to request.url as-is (fine for direct/local testing).
    TWILIO_PUBLIC_BASE_URL: str | None = None
    # Kill switch for the two WhatsApp webhook routes — defaults to False so
    # enabling WhatsApp inbound processing is an explicit opt-in, same
    # "secure/off by default" reasoning as DEV_AUTH_BYPASS above.
    WHATSAPP_WEBHOOK_ENABLED: bool = False

    # --- Outbound browser-to-phone calling (src/integrations/twilio_voice.py,
    # the Dial Pad on a Lead's "Log a call" modal) — shares
    # TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN above (same single Twilio account
    # as SMS/WhatsApp). Same "optional, validated at call-time" treatment:
    # unset, POST /leads/{id}/voice-token just returns a clear 503 instead
    # of failing startup.
    # API Key/Secret (Console -> Account -> API keys & tokens) — distinct
    # from ACCOUNT_SID/AUTH_TOKEN above (Twilio Access Tokens are always
    # signed with an API Key Secret, never the Account Auth Token directly);
    # used only to mint short-lived browser Voice Access Tokens (see
    # integrations/twilio_voice.py).
    TWILIO_VOICE_API_KEY_SID: str | None = None
    TWILIO_VOICE_API_KEY_SECRET: str | None = None
    # The TwiML App (Console -> Voice -> TwiML Apps) whose Voice Request URL
    # points at POST /voice/webhook/connect — this is what Twilio calls the
    # moment the browser's Voice SDK places a call, to learn what to dial.
    TWILIO_VOICE_TWIML_APP_SID: str | None = None
    # The Twilio Voice-capable number shown as caller ID on the outbound leg
    # to the Lead's phone.
    TWILIO_VOICE_CALLER_ID: str | None = None
    # Same role as TWILIO_PUBLIC_BASE_URL above, for the two voice webhooks
    # below — kept as its own value since the voice webhooks are a separate
    # TwiML App/URL from the WhatsApp ones, even though the Twilio account
    # itself is now shared. No default: never guess a production URL;
    # unset falls back to request.url as-is (fine for direct/local testing).
    TWILIO_VOICE_PUBLIC_BASE_URL: str | None = None

    # --- Inbound email-to-lead (src/services/inbound_email_client.py) ---
    # A dedicated, otherwise-unused mailbox — deliberately NOT the same
    # account as SMTP_USERNAME/SMTP_PASSWORD above. An actively-used mailbox
    # has real historical mail that "process everything unseen" would churn
    # through indiscriminately (and mark as read as a side effect) the first
    # time this runs; a dedicated inbox never has that backlog. Polled by
    # POST /email-intake/poll (see require_email_intake_secret below), meant
    # to be hit on a schedule (Cloud Scheduler in the real deployment), not
    # by a person — there's no live push subscription here.
    IMAP_HOST: str | None = None
    IMAP_PORT: int = 993
    IMAP_USERNAME: str | None = None
    IMAP_PASSWORD: str | None = None

    # Shared secret for POST /email-intake/poll — that caller is a scheduler,
    # not a logged-in employee, so there's no bearer token to check. Unlike
    # GATEWAY_CALLBACK_SECRET this is required in every environment (not just
    # prod): every successful call creates real Lead/Communication rows, so
    # "local dev" is not a safe place to leave this open. No default.
    EMAIL_INTAKE_SECRET: str | None = None

    # --- Sales Cadence scheduler (POST /cadence/advance-due-steps) ---
    # Shared secret that caller must present — same "scheduler, not a
    # logged-in employee, so no bearer token" reasoning as
    # EMAIL_INTAKE_SECRET above, and same "required in every environment"
    # treatment: every successful call auto-resolves real cadence tasks and
    # advances real enrollments. No default.
    CADENCE_SCHEDULER_SECRET: str | None = None
