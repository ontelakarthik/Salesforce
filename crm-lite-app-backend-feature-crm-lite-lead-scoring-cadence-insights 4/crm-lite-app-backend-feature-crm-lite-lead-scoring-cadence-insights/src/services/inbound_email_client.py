"""Inbound email fetching — the "capture" half of email-to-lead (crm_service.
run_email_intake(), POST /email-intake/poll). IMAPEmailReceiver is the
concrete provider: reads UNSEEN messages over IMAP from a dedicated mailbox
(IMAP_USERNAME/IMAP_PASSWORD) kept deliberately separate from the outbound
sender (SMTP_USERNAME/SMTP_PASSWORD in services/email_client.py) — an
actively-used mailbox accumulates real historical mail that "process
everything unseen" would churn through indiscriminately (and mark as read
as a side effect) the moment this is turned on; a dedicated inbox never has
that backlog. _MAX_MESSAGES_PER_POLL bounds the worst case regardless, so a
poll can never balloon into an hours-long job even if backlog does build up
later, marking each processed message \\Seen so it's never double-counted
across polls. Same Protocol-swap shape as EmailSender/LLMClient — a real
push subscription (Gmail API watch + Pub/Sub) could replace this later
without touching crm_service.py.

get_inbound_email_receiver() is a FastAPI dependency like get_email_sender()
— routes take it via Depends(get_inbound_email_receiver), and tests override
it with a fake since there's no real mailbox to poll in dev/CI.
"""
import email as email_lib
import imaplib
from datetime import datetime, timezone
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from typing import Protocol

from pydantic import BaseModel

from src.config.config_reader import get_settings
from src.utils.exceptions import DomainError


class InboundEmail(BaseModel):
    from_address: str
    from_name: str | None = None
    subject: str | None = None
    body: str | None = None
    received_at: datetime
    # RFC822 Message-ID header, when the sender's mail system set one — the
    # stable identifier crm_service.run_email_intake() dedups against
    # (Communication.graph_message_id), so re-polling the same message (e.g.
    # after its \Seen flag is reset) never creates a second Communication.
    message_id: str | None = None


class InboundEmailReceiver(Protocol):
    def fetch_unseen(self) -> list[InboundEmail]:
        """Raise DomainError on failure; return (possibly empty) list on success."""
        ...


#: Hard ceiling on messages processed in a single poll — independent of
#: which mailbox is configured. A dedicated mailbox should never see this
#: many unseen messages between 5-minute polls, but this is the difference
#: between "the next poll catches up" and "a poll turns into an hours-long
#: job that mangles a real backlog" if something ever goes wrong (the poll
#: schedule gets paused for a day, a bounce storm lands, etc.).
_MAX_MESSAGES_PER_POLL = 200


def _plain_text_body(msg: Message) -> str | None:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and part.get("Content-Disposition") is None:
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        return None
    if msg.get_content_type() != "text/plain":
        return None
    payload = msg.get_payload(decode=True)
    return payload.decode(msg.get_content_charset() or "utf-8", errors="replace") if payload else None


class IMAPEmailReceiver:
    def __init__(self, host: str, port: int, username: str, password: str) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password

    def fetch_unseen(self) -> list[InboundEmail]:
        try:
            with imaplib.IMAP4_SSL(self._host, self._port, timeout=20) as imap:
                imap.login(self._username, self._password)
                imap.select("INBOX")
                status, data = imap.search(None, "UNSEEN")
                if status != "OK":
                    raise DomainError("EMAIL_INTAKE_FAILED", f"IMAP search failed: {status}", 502)
                messages: list[InboundEmail] = []
                for num in data[0].split()[:_MAX_MESSAGES_PER_POLL]:
                    fetch_status, msg_data = imap.fetch(num, "(RFC822)")
                    if fetch_status != "OK" or not msg_data or msg_data[0] is None:
                        continue
                    parsed = email_lib.message_from_bytes(msg_data[0][1])
                    name, address = parseaddr(parsed.get("From", ""))
                    if not address:
                        continue
                    date_header = parsed.get("Date")
                    try:
                        received_at = parsedate_to_datetime(date_header) if date_header else None
                    except (TypeError, ValueError):
                        received_at = None
                    message_id = parsed.get("Message-ID")
                    messages.append(InboundEmail(
                        from_address=address.lower(), from_name=name or None,
                        subject=parsed.get("Subject"), body=_plain_text_body(parsed),
                        received_at=received_at or datetime.now(timezone.utc),
                        message_id=message_id.strip() if message_id else None,
                    ))
                    imap.store(num, "+FLAGS", "\\Seen")
                return messages
        except (imaplib.IMAP4.error, OSError) as exc:
            raise DomainError("EMAIL_INTAKE_FAILED", f"Could not fetch inbound email: {exc}", 502) from exc


def get_inbound_email_receiver() -> InboundEmailReceiver:
    settings = get_settings()
    if not settings.IMAP_HOST or not settings.IMAP_USERNAME or not settings.IMAP_PASSWORD:
        raise DomainError(
            "EMAIL_PROVIDER_NOT_CONFIGURED",
            "IMAP_HOST and IMAP_USERNAME/IMAP_PASSWORD are not set — add them to .env to enable "
            "inbound email capture.", 503)
    return IMAPEmailReceiver(settings.IMAP_HOST, settings.IMAP_PORT,
                             settings.IMAP_USERNAME, settings.IMAP_PASSWORD)
