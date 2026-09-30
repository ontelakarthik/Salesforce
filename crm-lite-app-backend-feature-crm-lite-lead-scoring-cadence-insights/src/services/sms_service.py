"""Outbound SMS-sending abstraction — the SMS action on a Lead's Cadence
Activity tab, a third Communication channel alongside logged calls and sent
emails (see activity_service.send_lead_sms()). Twilio's REST API is the
concrete provider; mirrors src/services/email_client.py's shape (a small
Protocol + one concrete class + a FastAPI dependency) so swapping providers
later means adding one more class here, never touching activity_service.py's
calling code.

get_sms_sender() is a FastAPI dependency like get_email_sender() — routes
take it via Depends(get_sms_sender), and tests override it with a fake (see
tests/test_sms_sending.py) since there's no real Twilio account configured
in dev/CI.
"""
from typing import Protocol

import httpx

from src.config.config_reader import get_settings
from src.utils.exceptions import DomainError

_TWILIO_TIMEOUT_SECONDS = 15

# SMS has no real "From" display-name field the way email does — the
# recipient's phone only ever shows TWILIO_FROM_NUMBER as a bare number
# (Alphanumeric Sender ID, Twilio's closest equivalent, isn't supported for
# two-way SMS in the US/Canada, which this feature needs for inbound
# replies — see crm_service.process_inbound_sms()). Prefixing the wire body
# is the only reliable way to identify the sender as CRM Lite in what the
# recipient actually reads. Deliberately applied here, not in
# activity_service.send_lead_sms(), so the Communication row keeps the
# rep's own typed text (what shows in the Activity tab) while the prefix is
# purely a wire-level thing the recipient sees.
_SENDER_PREFIX = "CRM Lite: "


class SmsSender(Protocol):
    def send(self, to_number: str, body: str) -> str:
        """Send one SMS; return the provider's message id (Twilio's `sid`).
        Raise DomainError on failure — a non-2xx provider response, or a
        network failure — never return on a failed send."""
        ...


class TwilioSmsSender:
    def __init__(self, account_sid: str, auth_token: str, from_number: str) -> None:
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._from_number = from_number

    def send(self, to_number: str, body: str) -> str:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self._account_sid}/Messages.json"
        try:
            response = httpx.post(
                url,
                auth=(self._account_sid, self._auth_token),
                # TEMPORARY: prefix removed so the body can exact-match a Twilio
                # trial-account predefined template during testing. Restore
                # `_SENDER_PREFIX + body` before shipping.
                data={"To": to_number, "From": self._from_number, "Body": body},
                timeout=_TWILIO_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise DomainError("SMS_SEND_FAILED", f"Could not reach Twilio: {exc}", 502) from exc

        if response.is_error:
            raise DomainError("SMS_SEND_FAILED", f"Twilio rejected the message: {_twilio_error(response)}", 502)

        return response.json()["sid"]


def _twilio_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text or f"HTTP {response.status_code}"
    return payload.get("message") or response.text or f"HTTP {response.status_code}"


def get_sms_sender() -> SmsSender:
    settings = get_settings()
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN or not settings.TWILIO_FROM_NUMBER:
        raise DomainError(
            "SMS_PROVIDER_NOT_CONFIGURED",
            "TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER are not set — "
            "add them to .env to enable sending SMS.", 503)
    return TwilioSmsSender(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN, settings.TWILIO_FROM_NUMBER)
