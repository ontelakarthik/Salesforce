"""Outbound WhatsApp-sending abstraction — Twilio-only boundary layer, no
database access here (see services/whatsapp_service.py for the Lead lookup/
Communication-persisting business logic that calls into this). Mirrors
services/sms_service.py's shape exactly (a small Protocol + one concrete
class + a FastAPI dependency), same reasoning: swapping providers later
means adding one more class here, never touching whatsapp_service.py's
calling code.

Twilio's WhatsApp channel uses the same Messages REST API as SMS, just with
a "whatsapp:" scheme prefix on both To/From — that prefix is added here
ONLY, and never allowed to leak into anything this integration returns or
into the database (see get_whatsapp_sender()/TwilioWhatsAppSender.send()).

Two send shapes, because WhatsApp itself has two: a free-form `Body`, only
allowed inside the 24-hour customer-service window (the lead messaged us
within the last 24h), and a Content Template (`ContentSid` +
`ContentVariables`) for everything else — Twilio rejects a free-form send
outside the window with "ContentSid Required". The template catalogue
itself comes from Twilio's Content API (TwilioContentTemplateSource below),
synced into the whatsapp_template table by
whatsapp_service.sync_whatsapp_templates().
"""
import json
from dataclasses import dataclass
from typing import Protocol

import httpx

from src.config.config_reader import get_settings
from src.utils.exceptions import DomainError

_TWILIO_TIMEOUT_SECONDS = 15
_WHATSAPP_PREFIX = "whatsapp:"
_CONTENT_AND_APPROVALS_URL = "https://content.twilio.com/v1/ContentAndApprovals?PageSize=500"

# Twilio's own WhatsApp approval status -> whatsapp_template.approval_status.
# Anything else ("unsubmitted", "received", "pending", "paused", ...) can't
# be sent yet, so it all collapses to PENDING.
_APPROVAL_STATUS_MAP = {"approved": "APPROVED", "rejected": "REJECTED"}


class WhatsAppSender(Protocol):
    def send(self, to_number: str, body: str) -> str:
        """Send one free-form WhatsApp message; `to_number` is a plain
        E.164 number (e.g. "+919876543210"), never "whatsapp:"-prefixed —
        that conversion happens inside this call only. Returns the
        provider's message id (Twilio's `sid`). Raises DomainError on
        failure — a non-2xx provider response, or a network failure —
        never returns on a failed send."""
        ...

    def send_template(self, to_number: str, content_sid: str, variables: dict[str, str]) -> str:
        """Send one approved Content Template (`content_sid`, e.g.
        "HXxxxxxxxx") with its {{1}}/{{2}}... substitutions. Same
        to_number/return/raise contract as send()."""
        ...


class TwilioWhatsAppSender:
    def __init__(self, account_sid: str, auth_token: str, from_number: str,
                 status_callback_url: str | None = None) -> None:
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._from_number = from_number
        self._status_callback_url = status_callback_url

    def send(self, to_number: str, body: str) -> str:
        return self._post(to_number, {"Body": body})

    def send_template(self, to_number: str, content_sid: str, variables: dict[str, str]) -> str:
        data = {"ContentSid": content_sid}
        if variables:
            data["ContentVariables"] = json.dumps(variables)
        return self._post(to_number, data)

    def _post(self, to_number: str, content: dict[str, str]) -> str:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self._account_sid}/Messages.json"
        data = {
            "To": _WHATSAPP_PREFIX + to_number,
            "From": _WHATSAPP_PREFIX + self._from_number,
            **content,
        }
        if self._status_callback_url:
            data["StatusCallback"] = self._status_callback_url
        try:
            response = httpx.post(
                url,
                auth=(self._account_sid, self._auth_token),
                data=data,
                timeout=_TWILIO_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise DomainError("WHATSAPP_SEND_FAILED", f"Could not reach Twilio: {exc}", 502) from exc

        if response.is_error:
            raise DomainError(
                "WHATSAPP_SEND_FAILED", f"Twilio rejected the message: {_twilio_error(response)}", 502)

        return response.json()["sid"]


def _twilio_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text or f"HTTP {response.status_code}"
    return payload.get("message") or response.text or f"HTTP {response.status_code}"


def get_whatsapp_sender() -> WhatsAppSender:
    """Reads the shared Twilio account credentials (TWILIO_ACCOUNT_SID/
    TWILIO_AUTH_TOKEN) — one Twilio account for SMS, WhatsApp and Voice, by
    this deployment's choice (see services/sms_service.py, which reads the
    same two settings). Only TWILIO_WHATSAPP_FROM (the sender identity) is
    WhatsApp-specific."""
    settings = get_settings()
    if (not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN
            or not settings.TWILIO_WHATSAPP_FROM):
        raise DomainError(
            "WHATSAPP_PROVIDER_NOT_CONFIGURED",
            "TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_FROM are not set — "
            "add them to .env to enable sending WhatsApp messages.", 503)
    status_callback_url = None
    if settings.TWILIO_PUBLIC_BASE_URL:
        status_callback_url = (
            settings.TWILIO_PUBLIC_BASE_URL.rstrip("/") + settings.API_PREFIX + "/whatsapp/webhook/status")
    return TwilioWhatsAppSender(
        settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN, settings.TWILIO_WHATSAPP_FROM,
        status_callback_url=status_callback_url)


# ---- Content Template catalogue (Twilio Content API) ----
@dataclass(frozen=True)
class FetchedTemplate:
    """One Twilio Content Template as the Content API reports it, already
    mapped onto whatsapp_template's columns (see
    activity_models.WhatsAppTemplate)."""
    content_sid: str
    name: str
    language: str
    category: str
    body_preview: str | None
    variable_count: int
    approval_status: str  # PENDING | APPROVED | REJECTED


class WhatsAppTemplateSource(Protocol):
    def fetch_templates(self) -> list[FetchedTemplate]:
        """Every Content Template on the Twilio account, with its WhatsApp
        approval status. Raises DomainError on a provider/network failure."""
        ...


class TwilioContentTemplateSource:
    def __init__(self, account_sid: str, auth_token: str) -> None:
        self._account_sid = account_sid
        self._auth_token = auth_token

    def fetch_templates(self) -> list[FetchedTemplate]:
        templates: list[FetchedTemplate] = []
        url: str | None = _CONTENT_AND_APPROVALS_URL
        while url:
            try:
                response = httpx.get(url, auth=(self._account_sid, self._auth_token),
                                     timeout=_TWILIO_TIMEOUT_SECONDS)
            except httpx.HTTPError as exc:
                raise DomainError("WHATSAPP_TEMPLATE_SYNC_FAILED", f"Could not reach Twilio: {exc}", 502) from exc
            if response.is_error:
                raise DomainError(
                    "WHATSAPP_TEMPLATE_SYNC_FAILED",
                    f"Twilio rejected the template listing: {_twilio_error(response)}", 502)
            payload = response.json()
            templates.extend(_parse_content(item) for item in payload.get("contents") or [])
            url = (payload.get("meta") or {}).get("next_page_url")
        return templates


def _parse_content(item: dict) -> FetchedTemplate:
    approval = item.get("approval_requests") or {}
    # `types` is keyed by content type ("twilio/text", "twilio/quick-reply",
    # "whatsapp/card", ...); every one a WhatsApp template can use carries a
    # `body` — the first one found is the preview.
    body = next((t["body"] for t in (item.get("types") or {}).values()
                 if isinstance(t, dict) and t.get("body")), None)
    return FetchedTemplate(
        content_sid=item["sid"],
        name=(approval.get("name") or item.get("friendly_name") or item["sid"])[:255],
        language=(item.get("language") or "en")[:10],
        category=(approval.get("category") or "UNCATEGORIZED").upper()[:20],
        body_preview=body[:1000] if body else None,
        variable_count=len(item.get("variables") or {}),
        approval_status=_APPROVAL_STATUS_MAP.get((approval.get("status") or "").lower(), "PENDING"),
    )


def get_whatsapp_template_source() -> WhatsAppTemplateSource:
    settings = get_settings()
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
        raise DomainError(
            "WHATSAPP_PROVIDER_NOT_CONFIGURED",
            "TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN are not set — "
            "add them to .env to sync WhatsApp templates.", 503)
    return TwilioContentTemplateSource(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
