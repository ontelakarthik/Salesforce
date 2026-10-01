"""Unit tests for IMAPEmailReceiver (services/inbound_email_client.py) — in
particular the _MAX_MESSAGES_PER_POLL cap. This exists because of a real
incident: polling a mailbox with tens of thousands of unseen messages tried
to fetch every single one in a loop, each fetch marking a message \\Seen as
a side effect, and the request ran until Cloud Run's own timeout killed it
mid-backlog. Mocked end-to-end (imaplib.IMAP4_SSL) rather than exercised via
HTTP — that's test_email_intake.py's job, with a fake InboundEmailReceiver —
since this only ever runs against a real mailbox in production.
"""
from unittest.mock import MagicMock, patch

import pytest

from src.services.inbound_email_client import IMAPEmailReceiver, _MAX_MESSAGES_PER_POLL
from src.utils.exceptions import DomainError


def _raw_message(from_address: str) -> bytes:
    return (
        f"From: Someone <{from_address}>\r\n"
        f"Subject: Hi\r\n"
        f"Date: Mon, 1 Jan 2026 00:00:00 +0000\r\n"
        f"Content-Type: text/plain\r\n\r\n"
        f"Body text.\r\n"
    ).encode()


def _mock_imap(unseen_count: int):
    mock_imap = MagicMock()
    mock_imap.__enter__.return_value = mock_imap
    # A real context manager doesn't swallow exceptions raised inside the
    # `with` block — MagicMock's auto-mocked __exit__ returns a (truthy)
    # MagicMock by default, which WOULD silently suppress them instead.
    mock_imap.__exit__.return_value = False
    mock_imap.search.return_value = ("OK", [b" ".join(str(i).encode() for i in range(unseen_count))])
    mock_imap.fetch.side_effect = lambda num, _: ("OK", [(b"1", _raw_message(f"sender{num.decode()}@example.com"))])
    return mock_imap


class TestMaxMessagesPerPoll:
    def test_stops_at_the_cap_even_with_a_much_larger_backlog(self):
        mock_imap = _mock_imap(unseen_count=_MAX_MESSAGES_PER_POLL * 50)
        with patch("src.services.inbound_email_client.imaplib.IMAP4_SSL", return_value=mock_imap):
            receiver = IMAPEmailReceiver("imap.example.com", 993, "user", "pass")
            messages = receiver.fetch_unseen()

        assert len(messages) == _MAX_MESSAGES_PER_POLL
        assert mock_imap.fetch.call_count == _MAX_MESSAGES_PER_POLL
        assert mock_imap.store.call_count == _MAX_MESSAGES_PER_POLL

    def test_processes_all_messages_when_under_the_cap(self):
        mock_imap = _mock_imap(unseen_count=3)
        with patch("src.services.inbound_email_client.imaplib.IMAP4_SSL", return_value=mock_imap):
            receiver = IMAPEmailReceiver("imap.example.com", 993, "user", "pass")
            messages = receiver.fetch_unseen()

        assert len(messages) == 3
        assert {m.from_address for m in messages} == {
            "sender0@example.com", "sender1@example.com", "sender2@example.com",
        }


class TestIMAPEmailReceiverErrors:
    def test_search_failure_is_a_clean_domain_error(self):
        mock_imap = MagicMock()
        mock_imap.__enter__.return_value = mock_imap
        mock_imap.__exit__.return_value = False
        mock_imap.search.return_value = ("NO", [None])
        with patch("src.services.inbound_email_client.imaplib.IMAP4_SSL", return_value=mock_imap):
            receiver = IMAPEmailReceiver("imap.example.com", 993, "user", "pass")
            with pytest.raises(DomainError) as exc_info:
                receiver.fetch_unseen()
        assert exc_info.value.code == "EMAIL_INTAKE_FAILED"

    def test_connection_failure_is_a_clean_domain_error(self):
        with patch("src.services.inbound_email_client.imaplib.IMAP4_SSL", side_effect=OSError("network unreachable")):
            receiver = IMAPEmailReceiver("imap.example.com", 993, "user", "pass")
            with pytest.raises(DomainError) as exc_info:
                receiver.fetch_unseen()
        assert exc_info.value.code == "EMAIL_INTAKE_FAILED"
