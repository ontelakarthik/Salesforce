"""Phone-number cleanup shared by Lead create/update and the Twilio send
paths (SMS, WhatsApp). Twilio wants E.164 ("+917330671971"); reps type
numbers however they like ("+91 7330671971", "+1 (512) 555-0101") — and on
a trial account Twilio rejects anything that isn't an exact match for a
verified number, spaces included.

Deliberately formatting-only: separators are stripped, nothing else is
guessed. A number typed without a country code stays without one, since
there's no reliable way to know which country it belongs to.
"""
import re

_SEPARATORS = re.compile(r"[\s\-().]")


def normalize_phone(value: str | None) -> str | None:
    """"+91 7330671971" -> "+917330671971"; blank -> None."""
    if value is None:
        return None
    cleaned = _SEPARATORS.sub("", value)
    return cleaned or None
