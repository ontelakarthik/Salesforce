"""Outbound email-sending abstraction — the "click send" half of AI-assisted
drafting (BRD AI-3/AT-1), and every system email (welcome emails, etc.).
SMTPEmailSender is the concrete provider (works with almost any mailbox —
O365, Gmail, SendGrid's SMTP endpoint — via five settings, no app
registration); swapping providers later means adding one more class here,
never touching activity_service.py's/admin_service.py's calling code.

Domain-wide delegation via a GCP service account (impersonating a Workspace
mailbox through the Gmail API) was tried and ruled out: it needs either a
downloadable service-account key or IAM's signBlob-based remote signing to
work, and this org's IAM policy blocks both (confirmed live — signBlob was
denied even for a project Owner). Real Gmail sending here goes through
Gmail's own SMTP relay with a real mailbox's App Password instead — same
SMTPEmailSender class, just SMTP_HOST=smtp.gmail.com.

get_email_sender() is a FastAPI dependency like get_llm_client() — routes
take it via Depends(get_email_sender), and tests override it with a fake
(see tests/test_email_sending.py) since there's no real mail provider
configured in dev/CI.
"""
import smtplib
from email.message import EmailMessage
from typing import Protocol

from src.config.config_reader import get_settings
from src.utils.exceptions import DomainError


class EmailSender(Protocol):
    def send(self, to_address: str, subject: str, body: str) -> None:
        """Raise DomainError on failure; return normally on success."""
        ...


class SMTPEmailSender:
    def __init__(self, host: str, port: int, username: str | None, password: str | None,
                from_address: str) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._from_address = from_address

    def send(self, to_address: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self._from_address
        message["To"] = to_address
        message.set_content(body)
        try:
            with smtplib.SMTP(self._host, self._port, timeout=15) as smtp:
                smtp.starttls()
                if self._username and self._password:
                    smtp.login(self._username, self._password)
                smtp.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            raise DomainError("EMAIL_SEND_FAILED", f"Could not send the email: {exc}", 502) from exc


def get_email_sender() -> EmailSender:
    settings = get_settings()
    if not settings.SMTP_HOST or not settings.SMTP_FROM_ADDRESS:
        raise DomainError(
            "EMAIL_PROVIDER_NOT_CONFIGURED",
            "SMTP_HOST and SMTP_FROM_ADDRESS are not set — add them to .env to enable sending email.", 503)
    return SMTPEmailSender(settings.SMTP_HOST, settings.SMTP_PORT, settings.SMTP_USERNAME,
                           settings.SMTP_PASSWORD, settings.SMTP_FROM_ADDRESS)


def get_optional_email_sender() -> EmailSender | None:
    """Same as get_email_sender(), but for call sites where "email isn't
    configured" shouldn't fail the whole request (see admin_service.
    create_employee() — a welcome email failing to send must never undo the
    employee it's for) — None instead of a 503 dependency-resolution error."""
    try:
        return get_email_sender()
    except DomainError:
        return None
