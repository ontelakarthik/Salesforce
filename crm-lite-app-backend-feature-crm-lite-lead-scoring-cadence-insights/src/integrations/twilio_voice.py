"""Twilio Voice boundary layer — browser-to-phone calling for the Dial Pad
on a Lead's "Log a call" modal. No database access here (see
services/voice_service.py for the Lead lookup/Communication-persisting
business logic that calls into this).

Unlike sms_service.py/twilio_whatsapp.py (which POST to Twilio's REST API),
minting a browser Access Token is pure local JWT signing — no network call
to Twilio at all — so this uses pyjwt (already a project dependency, used
for this app's own auth JWTs in utils/security.py) rather than adding the
Twilio Python SDK as a new dependency, matching the project's established
"no Twilio SDK" convention.

Twilio's Access Token format: https://www.twilio.com/docs/iam/access-tokens
— a JWT with a `cty: twilio-fpa;v=1` header and a `grants.voice` claim
naming the TwiML App to route outgoing calls to.
"""
import uuid
from datetime import datetime, timedelta, timezone
from xml.etree.ElementTree import Element, SubElement, tostring

import jwt

from src.config.config_reader import get_settings
from src.utils.exceptions import DomainError

_TOKEN_TTL = timedelta(hours=1)

#: Twilio CallStatus values that are ever seen on a status callback.
#: https://www.twilio.com/docs/voice/api/call-resource#call-status-values
TERMINAL_CALL_STATUSES = {"completed", "busy", "no-answer", "failed", "canceled"}

#: Maps Twilio's CallStatus to this project's existing call_disposition
#: lookup codes (seeded set: CONNECTED, VOICEMAIL, NO_ANSWER, BUSY,
#: WRONG_NUMBER, OTHER — see activity_models.CallDisposition) — reusing the
#: existing vocabulary rather than inventing new outcome values. Twilio has
#: no signal that distinguishes "voicemail"/"wrong number" from a normal
#: connected call, so those two existing codes are simply never
#: Twilio-driven; only a human logging a call manually would ever set them.
_STATUS_TO_DISPOSITION_CODE = {
    "completed": "CONNECTED",
    "busy": "BUSY",
    "no-answer": "NO_ANSWER",
    "failed": "OTHER",
    "canceled": "OTHER",
}

#: Friendly translations for the Twilio error codes a rep is actually
#: likely to hit on a trial/free account — never hide the real error, just
#: make the common ones legible. Anything not listed here still surfaces
#: (see services/voice_service.py), just without a translated message.
FRIENDLY_ERROR_MESSAGES = {
    "21215": "Twilio trial accounts can only call phone numbers that have "
             "been verified in the Twilio Console (Phone Numbers -> Verified Caller IDs).",
    "21211": "The phone number entered is not valid.",
    "13224": "The phone number entered is not a valid phone number.",
    "13223": "The call could not be completed — the destination number appears to be unreachable.",
}


def map_call_status_to_disposition_code(call_status: str) -> str | None:
    """None for a non-terminal status (initiated/ringing/in-progress) —
    the CRM call_outcome only reflects Twilio's data once the call actually
    reaches a final state, never a live in-progress one."""
    return _STATUS_TO_DISPOSITION_CODE.get(call_status)


def friendly_error_message(error_code: str | None) -> str | None:
    if not error_code:
        return None
    return FRIENDLY_ERROR_MESSAGES.get(error_code)


def mint_access_token(identity: str) -> str:
    """A short-lived token the browser's Twilio Voice SDK uses to register
    a Device and place outgoing calls through TWILIO_VOICE_TWIML_APP_SID —
    never a Twilio Auth Token/API Secret, which stay backend-only. `identity`
    is this app's own employee id; Twilio prefixes it with "client:" as the
    `From` it hands to the TwiML App's Voice Request URL (see
    server/crm_routes.py's connect webhook)."""
    settings = get_settings()
    if not (settings.TWILIO_ACCOUNT_SID and settings.TWILIO_VOICE_API_KEY_SID
            and settings.TWILIO_VOICE_API_KEY_SECRET and settings.TWILIO_VOICE_TWIML_APP_SID):
        raise DomainError(
            "VOICE_PROVIDER_NOT_CONFIGURED",
            "TWILIO_ACCOUNT_SID, TWILIO_VOICE_API_KEY_SID, TWILIO_VOICE_API_KEY_SECRET "
            "and TWILIO_VOICE_TWIML_APP_SID are not set — add them to .env to enable calling.", 503)

    now = datetime.now(timezone.utc)
    payload = {
        "jti": f"{settings.TWILIO_VOICE_API_KEY_SID}-{uuid.uuid4().hex}",
        "iss": settings.TWILIO_VOICE_API_KEY_SID,
        "sub": settings.TWILIO_ACCOUNT_SID,
        "iat": now,
        "exp": now + _TOKEN_TTL,
        "grants": {
            "identity": identity,
            "voice": {
                "outgoing": {"application_sid": settings.TWILIO_VOICE_TWIML_APP_SID},
                # No incoming calls to the browser — this feature is
                # outbound-only (Dial Pad), never a call center inbox.
                "incoming": {"allow": False},
            },
        },
    }
    return jwt.encode(payload, settings.TWILIO_VOICE_API_KEY_SECRET, algorithm="HS256",
                      headers={"cty": "twilio-fpa;v=1"})


def build_connect_twiml(*, to_number: str, caller_id: str, status_callback_url: str | None) -> str:
    """TwiML returned from the connect webhook — tells Twilio to dial
    `to_number` and bridge it to the browser call already in progress.
    Built with stdlib ElementTree (not string formatting) so the phone
    number is always properly XML-escaped, no new templating dependency."""
    response = Element("Response")
    dial = SubElement(response, "Dial", {"callerId": caller_id})
    number_attrs = {}
    if status_callback_url:
        number_attrs = {
            "statusCallback": status_callback_url,
            "statusCallbackMethod": "POST",
            "statusCallbackEvent": "initiated ringing answered completed",
        }
    number = SubElement(dial, "Number", number_attrs)
    number.text = to_number
    return '<?xml version="1.0" encoding="UTF-8"?>' + tostring(response, encoding="unicode")


def get_voice_public_base_url() -> str | None:
    return get_settings().TWILIO_VOICE_PUBLIC_BASE_URL


def get_voice_caller_id() -> str | None:
    return get_settings().TWILIO_VOICE_CALLER_ID
