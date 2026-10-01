"""Real WhatsApp sending — the WhatsApp action on a Lead's Activity tab
(services/whatsapp_service.send_lead_whatsapp(), backed by
src/integrations/twilio_whatsapp.py). Mirrors tests/test_sms_sending.py's
shape exactly: the "not configured" 503 path is simulated via
app.dependency_overrides rather than assumed from the ambient environment,
and the happy path is tested via a fake WhatsAppSender through the same
mechanism.
"""
import uuid

from src.server import app
from src.integrations.twilio_whatsapp import get_whatsapp_sender, get_whatsapp_template_source
from src.repositories.activity_repository import get_whatsapp_template_repository
from src.utils.exceptions import DomainError


def _lead(client, headers, **overrides):
    payload = {"company_name": "Meridian Health", "contact_email": f"{uuid.uuid4().hex[:8]}@meridianhealth.example",
              "first_name": "Ananya", "last_name": "Rao"} | overrides
    r = client.post("/api/v1/leads", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


class _FakeWhatsAppSender:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.sent: list[tuple[str, str]] = []

    def send(self, to_number: str, body: str) -> str:
        if self.fail:
            raise DomainError("WHATSAPP_SEND_FAILED", "simulated failure", 502)
        self.sent.append((to_number, body))
        # Unique per call, not a fixed literal — this test DB has no
        # per-test rollback (a persistent shared Postgres, see conftest.py),
        # and provider_message_id now has a real unique index (added for
        # webhook idempotency), so a fixed SID would collide with whatever
        # a prior run already left behind.
        return f"SMfakewhatsapp{uuid.uuid4().hex}"

    def send_template(self, to_number: str, content_sid: str, variables: dict[str, str]) -> str:
        if self.fail:
            raise DomainError("WHATSAPP_SEND_FAILED", "simulated failure", 502)
        self.sent.append((to_number, content_sid))
        return f"SMfakewhatsapp{uuid.uuid4().hex}"


def _override(fake):
    app.dependency_overrides[get_whatsapp_sender] = lambda: fake


def _clear_override():
    app.dependency_overrides.pop(get_whatsapp_sender, None)


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
                "WHATSAPP_PROVIDER_NOT_CONFIGURED",
                "TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_FROM are not set — "
                "add them to .env to enable sending WhatsApp messages.", 503)
        app.dependency_overrides[get_whatsapp_sender] = _raise

        lead = _lead(client, admin_headers, whatsapp_number="+15551234567")
        r = client.post(f"/api/v1/leads/{lead['id']}/whatsapp", json={"body": "Hi there"}, headers=admin_headers)
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "WHATSAPP_PROVIDER_NOT_CONFIGURED"


class TestSendHappyPath:
    def teardown_method(self):
        _clear_override()

    def test_sends_and_logs_communication(self, client, admin_headers):
        fake = _FakeWhatsAppSender()
        _override(fake)
        lead = _lead(client, admin_headers, whatsapp_number="+15551234567")

        r = client.post(f"/api/v1/leads/{lead['id']}/whatsapp", json={"body": "Following up"}, headers=admin_headers)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["channel"] == "WHATSAPP"
        assert body["direction"] == "OUTBOUND"
        assert body["body"] == "Following up"
        assert body["to_recipients"] == "+15551234567"
        assert body["lead_id"] == lead["id"]
        assert body["provider_message_id"].startswith("SMfakewhatsapp")
        # Twilio's "whatsapp:" wire prefix must never leak into what we send/store.
        assert fake.sent == [("+15551234567", "Following up")]

        comms = client.get(f"/api/v1/leads/{lead['id']}/communications", headers=admin_headers).json()
        assert comms[0]["channel"] == "WHATSAPP"
        assert comms[0]["provider_message_id"] == body["provider_message_id"]

    def test_no_whatsapp_number_on_file_is_422_before_any_provider_call(self, client, admin_headers):
        fake = _FakeWhatsAppSender()
        _override(fake)
        lead = _lead(client, admin_headers)  # no whatsapp_number

        r = client.post(f"/api/v1/leads/{lead['id']}/whatsapp", json={"body": "Hi"}, headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "WHATSAPP_RECIPIENT_MISSING"
        assert fake.sent == []

    def test_provider_failure_does_not_log_a_communication(self, client, admin_headers):
        _override(_FakeWhatsAppSender(fail=True))
        lead = _lead(client, admin_headers, whatsapp_number="+15551234567")

        r = client.post(f"/api/v1/leads/{lead['id']}/whatsapp", json={"body": "Hi"}, headers=admin_headers)
        # A brand-new lead has never messaged us, so its 24-hour window is
        # closed and a rejected free-form send is reported as needing a template.
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "WHATSAPP_TEMPLATE_REQUIRED"

        comms = client.get(f"/api/v1/leads/{lead['id']}/communications", headers=admin_headers).json()
        assert comms == []  # a failed send must not create a false activity record

    def test_sales_cannot_send_for_unowned_lead(self, client, admin_headers, sales_headers):
        _override(_FakeWhatsAppSender())
        lead = _lead(client, admin_headers, whatsapp_number="+15551234567")  # owner unset

        r = client.post(f"/api/v1/leads/{lead['id']}/whatsapp", json={"body": "Hi"}, headers=sales_headers)
        assert r.status_code == 403


class TestTemplateRoutes:
    def teardown_method(self):
        _clear_override()
        app.dependency_overrides.pop(get_whatsapp_template_source, None)

    def _approved_template(self, **overrides):
        fields = {"name": f"test_template_{uuid.uuid4().hex[:8]}", "content_sid": f"HX{uuid.uuid4().hex}",
                  "category": "UTILITY", "body_preview": "Hi {{1}}", "variable_count": 1,
                  "approval_status": "APPROVED", "is_active": True, "created_by": "test", "updated_by": "test"}
        return get_whatsapp_template_repository().create(**(fields | overrides))

    def test_template_send_logs_rendered_body(self, client, admin_headers):
        fake = _FakeWhatsAppSender()
        _override(fake)
        template = self._approved_template()
        lead = _lead(client, admin_headers, whatsapp_number="+15551234567")

        r = client.post(f"/api/v1/leads/{lead['id']}/whatsapp",
                        json={"template_id": str(template.id), "template_variables": {"1": "Ananya"}},
                        headers=admin_headers)
        assert r.status_code == 201, r.text
        assert r.json()["body"] == "Hi Ananya"
        assert r.json()["whatsapp_template_id"] == str(template.id)
        assert fake.sent == [("+15551234567", template.content_sid)]

    def test_list_only_returns_approved_active(self, client, admin_headers):
        approved = self._approved_template()
        pending = self._approved_template(approval_status="PENDING")
        r = client.get("/api/v1/whatsapp/templates", headers=admin_headers)
        assert r.status_code == 200, r.text
        ids = {t["id"] for t in r.json()}
        assert str(approved.id) in ids
        assert str(pending.id) not in ids

    def test_sync_is_admin_only(self, client, sales_headers):
        app.dependency_overrides[get_whatsapp_template_source] = lambda: None
        r = client.post("/api/v1/whatsapp/templates/sync", headers=sales_headers)
        assert r.status_code == 403


class TestValidation:
    """422 before any provider call — a Pydantic-level check. Overrides
    get_whatsapp_sender with a fake anyway (unlike test_sms_sending.py's
    equivalent) so this passes regardless of whether TWILIO_WHATSAPP_*
    happens to be configured in the ambient .env — a genuinely unconfigured
    provider 503s during dependency resolution before body validation ever
    runs, which would otherwise make this test depend on ambient state."""

    def teardown_method(self):
        _clear_override()

    def test_empty_body_is_422(self, client, admin_headers):
        _override(_FakeWhatsAppSender())
        lead = _lead(client, admin_headers, whatsapp_number="+15551234567")
        r = client.post(f"/api/v1/leads/{lead['id']}/whatsapp", json={"body": ""}, headers=admin_headers)
        assert r.status_code == 422

    def test_over_length_body_is_422(self, client, admin_headers):
        _override(_FakeWhatsAppSender())
        lead = _lead(client, admin_headers, whatsapp_number="+15551234567")
        r = client.post(f"/api/v1/leads/{lead['id']}/whatsapp", json={"body": "x" * 1601}, headers=admin_headers)
        assert r.status_code == 422
