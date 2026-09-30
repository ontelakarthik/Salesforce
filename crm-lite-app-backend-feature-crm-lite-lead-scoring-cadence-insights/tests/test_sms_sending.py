"""Real SMS sending — the SMS action on a Lead's Cadence Activity tab
(activity_service.send_lead_sms(), backed by services/sms_service.py). Mirrors
tests/test_email_sending.py's shape exactly: the "not configured" 503 and
"provider rejected it" 502 paths are simulated via app.dependency_overrides
rather than assumed from the ambient environment, and the happy path is
tested via a fake SmsSender through the same mechanism.
"""
import uuid

from src.server import app
from src.services.sms_service import get_sms_sender
from src.utils.exceptions import DomainError


def _lead(client, headers, **overrides):
    payload = {"company_name": "Meridian Health", "contact_email": "test.lead@example.com",
              "first_name": "Ananya", "last_name": "Rao"} | overrides
    r = client.post("/api/v1/leads", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


class _FakeSmsSender:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.sent: list[tuple[str, str]] = []
        self.sent_ids: list[str] = []

    def send(self, to_number: str, body: str) -> str:
        if self.fail:
            raise DomainError("SMS_SEND_FAILED", "simulated failure", 502)
        self.sent.append((to_number, body))
        # uuid-suffixed, not a fixed literal — communication.provider_message_id
        # is unique, and this test DB has no per-test rollback (a persistent
        # shared Postgres, see tests/test_sms_intake.py's module docstring),
        # so a fixed value collides with the row a prior run already left
        # behind.
        message_id = f"SMfake{uuid.uuid4().hex}"
        self.sent_ids.append(message_id)
        return message_id


def _override(fake):
    app.dependency_overrides[get_sms_sender] = lambda: fake


def _clear_override():
    app.dependency_overrides.pop(get_sms_sender, None)


class TestNotConfigured:
    """Simulated via dependency override rather than relying on the ambient
    .env having no Twilio credentials — a dev doing manual send-testing
    against a real Twilio account would otherwise make this path silently
    go live."""

    def teardown_method(self):
        _clear_override()

    def test_503s_when_twilio_not_configured(self, client, admin_headers):
        def _raise():
            raise DomainError(
                "SMS_PROVIDER_NOT_CONFIGURED",
                "TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER are not set — "
                "add them to .env to enable sending SMS.", 503)
        app.dependency_overrides[get_sms_sender] = _raise

        lead = _lead(client, admin_headers, contact_phone="+15551234567")
        r = client.post(f"/api/v1/leads/{lead['id']}/sms", json={"message": "Hi there"}, headers=admin_headers)
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "SMS_PROVIDER_NOT_CONFIGURED"


class TestSendHappyPath:
    def teardown_method(self):
        _clear_override()

    def test_sends_and_logs_communication(self, client, admin_headers):
        fake = _FakeSmsSender()
        _override(fake)
        lead = _lead(client, admin_headers, contact_phone="+15551234567")

        r = client.post(f"/api/v1/leads/{lead['id']}/sms", json={"message": "Following up"}, headers=admin_headers)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["channel"] == "SMS"
        assert body["direction"] == "OUTBOUND"
        assert body["body"] == "Following up"
        assert body["to_recipients"] == "+15551234567"
        assert body["lead_id"] == lead["id"]
        assert body["provider_message_id"] == fake.sent_ids[0]
        assert fake.sent == [("+15551234567", "Following up")]

        comms = client.get(f"/api/v1/leads/{lead['id']}/communications", headers=admin_headers).json()
        assert comms[0]["channel"] == "SMS"
        assert comms[0]["provider_message_id"] == fake.sent_ids[0]

    def test_falls_back_to_mobile_phone_when_contact_phone_missing(self, client, admin_headers):
        fake = _FakeSmsSender()
        _override(fake)
        lead = _lead(client, admin_headers, mobile_phone="+15559876543")

        r = client.post(f"/api/v1/leads/{lead['id']}/sms", json={"message": "Hi"}, headers=admin_headers)
        assert r.status_code == 201, r.text
        assert r.json()["to_recipients"] == "+15559876543"
        assert fake.sent[0][0] == "+15559876543"

    def test_no_phone_on_file_is_422_before_any_provider_call(self, client, admin_headers):
        fake = _FakeSmsSender()
        _override(fake)
        lead = _lead(client, admin_headers)  # no contact_phone/mobile_phone

        r = client.post(f"/api/v1/leads/{lead['id']}/sms", json={"message": "Hi"}, headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "SMS_RECIPIENT_MISSING"
        assert fake.sent == []

    def test_provider_failure_does_not_log_a_communication(self, client, admin_headers):
        _override(_FakeSmsSender(fail=True))
        lead = _lead(client, admin_headers, contact_phone="+15551234567")

        r = client.post(f"/api/v1/leads/{lead['id']}/sms", json={"message": "Hi"}, headers=admin_headers)
        assert r.status_code == 502
        assert r.json()["error"]["code"] == "SMS_SEND_FAILED"

        comms = client.get(f"/api/v1/leads/{lead['id']}/communications", headers=admin_headers).json()
        assert comms == []  # a failed send must not create a false activity record

    def test_sales_cannot_send_for_unowned_lead(self, client, admin_headers, sales_headers):
        _override(_FakeSmsSender())
        lead = _lead(client, admin_headers, contact_phone="+15551234567")  # owner unset

        r = client.post(f"/api/v1/leads/{lead['id']}/sms", json={"message": "Hi"}, headers=sales_headers)
        assert r.status_code == 403


class TestValidation:
    """422 before any provider call — a Pydantic-level check. Still overrides
    get_sms_sender (like TestSendHappyPath) rather than relying on the
    ambient .env having real Twilio credentials: FastAPI resolves
    Depends(get_sms_sender) regardless of whether the body later fails
    Pydantic validation, so an unconfigured/cleared ambient TWILIO_AUTH_TOKEN
    (e.g. left behind by another test module's teardown) would 503 here
    instead of 422 — these tests want to isolate the validation behavior
    from that unrelated dependency."""

    def teardown_method(self):
        _clear_override()

    def test_empty_message_is_422(self, client, admin_headers):
        _override(_FakeSmsSender())
        lead = _lead(client, admin_headers, contact_phone="+15551234567")
        r = client.post(f"/api/v1/leads/{lead['id']}/sms", json={"message": ""}, headers=admin_headers)
        assert r.status_code == 422

    def test_over_length_message_is_422(self, client, admin_headers):
        _override(_FakeSmsSender())
        lead = _lead(client, admin_headers, contact_phone="+15551234567")
        r = client.post(f"/api/v1/leads/{lead['id']}/sms", json={"message": "x" * 1601}, headers=admin_headers)
        assert r.status_code == 422
