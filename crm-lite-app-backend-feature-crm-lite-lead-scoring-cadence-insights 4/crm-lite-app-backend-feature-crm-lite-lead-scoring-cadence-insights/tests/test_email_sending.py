"""Real email sending (BRD AI-3's "click send" flow) — activity_service.
send_lead_email(), backed by services/email_client.py. The "not configured"
503 path is simulated via app.dependency_overrides rather than assumed from
the ambient environment (a dev doing manual send-testing may well have real
SMTP creds in .env), and the happy path is tested via a fake EmailSender
through the same mechanism (see test_ai_drafting.py for the identical
pattern against the LLM client).
"""
from src.server import app
from src.services.email_client import get_email_sender
from src.utils.exceptions import DomainError


def _lead(client, headers, **overrides):
    payload = {"company_name": "Meridian Health", "contact_email": "test.lead@example.com", "first_name": "Ananya", "last_name": "Rao"} | overrides
    r = client.post("/api/v1/leads", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


class _FakeEmailSender:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.sent: list[tuple[str, str, str]] = []

    def send(self, to_address: str, subject: str, body: str) -> None:
        if self.fail:
            from src.utils.exceptions import DomainError
            raise DomainError("EMAIL_SEND_FAILED", "simulated failure", 502)
        self.sent.append((to_address, subject, body))


def _override(fake):
    app.dependency_overrides[get_email_sender] = lambda: fake


def _clear_override():
    app.dependency_overrides.pop(get_email_sender, None)


class TestNotConfigured:
    """Simulated via dependency override rather than relying on the ambient
    .env having no SMTP_HOST — a dev doing manual send-testing against a
    real relay would otherwise make this path silently go live."""

    def teardown_method(self):
        _clear_override()

    def test_503s_when_smtp_not_configured(self, client, admin_headers):
        def _raise():
            raise DomainError(
                "EMAIL_PROVIDER_NOT_CONFIGURED",
                "SMTP_HOST and SMTP_FROM_ADDRESS are not set — add them to .env to enable sending email.", 503)
        app.dependency_overrides[get_email_sender] = _raise

        lead = _lead(client, admin_headers, contact_email="jordan@example.com")
        r = client.post(f"/api/v1/leads/{lead['id']}/communications/send",
                        json={"subject": "Hi", "body": "Hello there"}, headers=admin_headers)
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "EMAIL_PROVIDER_NOT_CONFIGURED"


class TestSendHappyPath:
    def teardown_method(self):
        _clear_override()

    def test_sends_and_logs_communication(self, client, admin_headers):
        fake = _FakeEmailSender()
        _override(fake)
        lead = _lead(client, admin_headers, contact_email="jordan@example.com")

        r = client.post(f"/api/v1/leads/{lead['id']}/communications/send",
                        json={"subject": "Following up", "body": "Hi Jordan, ..."}, headers=admin_headers)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["channel"] == "EMAIL"
        assert body["direction"] == "OUTBOUND"
        assert body["subject"] == "Following up"
        assert body["body"] == "Hi Jordan, ..."
        assert body["to_recipients"] == "jordan@example.com"
        assert body["lead_id"] == lead["id"]
        assert fake.sent == [("jordan@example.com", "Following up", "Hi Jordan, ...")]

        # the full sent email is retrievable from the lead's activity history,
        # not just its subject
        comms = client.get(f"/api/v1/leads/{lead['id']}/communications", headers=admin_headers).json()
        assert comms[0]["body"] == "Hi Jordan, ..."

        # sent emails feed Email Insights the same as manually-logged ones
        insights = client.get(f"/api/v1/leads/{lead['id']}/email-insights", headers=admin_headers).json()
        assert insights["total_emails"] == 1
        assert insights["outbound_count"] == 1

    def test_explicit_to_address_overrides_lead_contact_email(self, client, admin_headers):
        fake = _FakeEmailSender()
        _override(fake)
        lead = _lead(client, admin_headers, contact_email="jordan@example.com")

        r = client.post(f"/api/v1/leads/{lead['id']}/communications/send",
                        json={"subject": "Hi", "body": "B", "to_address": "override@example.com"},
                        headers=admin_headers)
        assert r.status_code == 201
        assert r.json()["to_recipients"] == "override@example.com"
        assert fake.sent[0][0] == "override@example.com"

    def test_provider_failure_does_not_log_a_communication(self, client, admin_headers):
        _override(_FakeEmailSender(fail=True))
        lead = _lead(client, admin_headers, contact_email="jordan@example.com")

        r = client.post(f"/api/v1/leads/{lead['id']}/communications/send",
                        json={"subject": "Hi", "body": "B"}, headers=admin_headers)
        assert r.status_code == 502
        assert r.json()["error"]["code"] == "EMAIL_SEND_FAILED"

        insights = client.get(f"/api/v1/leads/{lead['id']}/email-insights", headers=admin_headers).json()
        assert insights["total_emails"] == 0  # a failed send must not create a false activity record

    def test_sales_cannot_send_for_unowned_lead(self, client, admin_headers, sales_headers):
        _override(_FakeEmailSender())
        lead = _lead(client, admin_headers, contact_email="jordan@example.com")  # owner unset

        r = client.post(f"/api/v1/leads/{lead['id']}/communications/send",
                        json={"subject": "Hi", "body": "B"}, headers=sales_headers)
        assert r.status_code == 403
