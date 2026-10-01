"""Inbound WhatsApp-to-lead (POST /whatsapp/webhook/inbound) and the
delivery-status callback (POST /whatsapp/webhook/status). One Twilio
webhook call per inbound message, matched against Lead.whatsapp_number.
Mirrors tests/test_sms_intake.py's shape exactly, plus TWILIO_PUBLIC_BASE_URL
signature-reconstruction and 24-hour-window coverage this feature adds on
top of the SMS precedent.

Every test signs its own request exactly the way Twilio actually would
(independently of utils.security._twilio_signature, so this isn't a
tautological test of the same code it's meant to check), and sets
TWILIO_AUTH_TOKEN/WHATSAPP_WEBHOOK_ENABLED/TWILIO_PUBLIC_BASE_URL explicitly
rather than relying on the ambient environment — WhatsApp signs with the
same shared TWILIO_AUTH_TOKEN as SMS (one Twilio account for both, by this
deployment's choice).

WhatsApp numbers are uuid-suffixed throughout — this test DB has no
per-test rollback (a persistent shared Postgres, see conftest.py), so a
fixed literal number would collide with a lead a prior run already left
behind.
"""
import base64
import hashlib
import hmac
import uuid

from src.config.config_reader import get_settings

_AUTH_TOKEN = "test-twilio-auth-token"
_PUBLIC_BASE_URL = "https://public.example.com"
_INBOUND_URL = f"{_PUBLIC_BASE_URL}/api/v1/whatsapp/webhook/inbound"
_STATUS_URL = f"{_PUBLIC_BASE_URL}/api/v1/whatsapp/webhook/status"


def _whatsapp_number() -> str:
    # Not a real E.164 number, but unique and stable enough to round-trip
    # through Lead.whatsapp_number / the webhook's From field for a test.
    return f"+1555{uuid.uuid4().int % 10_000_000:07d}"


def _sign(url: str, params: dict[str, str], token: str) -> str:
    data = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    digest = hmac.new(token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


def _post_inbound(client, params: dict[str, str], *, token: str = _AUTH_TOKEN, signature: str | None = None):
    sig = signature if signature is not None else _sign(_INBOUND_URL, params, token)
    return client.post("/api/v1/whatsapp/webhook/inbound", data=params, headers={"X-Twilio-Signature": sig})


def _post_status(client, params: dict[str, str], *, token: str = _AUTH_TOKEN, signature: str | None = None):
    sig = signature if signature is not None else _sign(_STATUS_URL, params, token)
    return client.post("/api/v1/whatsapp/webhook/status", data=params, headers={"X-Twilio-Signature": sig})


def setup_module():
    settings = get_settings()
    settings.TWILIO_AUTH_TOKEN = _AUTH_TOKEN
    settings.WHATSAPP_WEBHOOK_ENABLED = True
    settings.TWILIO_PUBLIC_BASE_URL = _PUBLIC_BASE_URL


def teardown_module():
    settings = get_settings()
    settings.TWILIO_AUTH_TOKEN = None
    settings.WHATSAPP_WEBHOOK_ENABLED = False
    settings.TWILIO_PUBLIC_BASE_URL = None


class TestWebhookDisabled:
    def test_503s_when_webhook_disabled(self, client):
        get_settings().WHATSAPP_WEBHOOK_ENABLED = False
        try:
            r = _post_inbound(client, {"From": "whatsapp:+15551234567", "Body": "Hi", "MessageSid": "SM123"})
            assert r.status_code == 503
            assert r.json()["error"]["code"] == "WHATSAPP_NOT_CONFIGURED"
        finally:
            get_settings().WHATSAPP_WEBHOOK_ENABLED = True


class TestSignatureAuth:
    def test_missing_signature_is_rejected(self, client):
        r = client.post("/api/v1/whatsapp/webhook/inbound", data={"From": "whatsapp:+15551234567", "Body": "Hi"})
        assert r.status_code == 403

    def test_wrong_signature_is_rejected(self, client):
        r = _post_inbound(client, {"From": "whatsapp:+15551234567", "Body": "Hi", "MessageSid": "SM123"},
                          signature="bogus")
        assert r.status_code == 403

    def test_signature_computed_against_raw_request_url_is_rejected(self, client):
        """Must validate against TWILIO_PUBLIC_BASE_URL, not request.url as
        Starlette sees it (which behind a proxy could be an internal http://
        URL Twilio never actually signed) — see
        utils.security.require_twilio_whatsapp_signature."""
        params = {"From": "whatsapp:+15551234567", "Body": "Hi", "MessageSid": "SM123"}
        wrong_url_sig = _sign("http://testserver/api/v1/whatsapp/webhook/inbound", params, _AUTH_TOKEN)
        r = _post_inbound(client, params, signature=wrong_url_sig)
        assert r.status_code == 403

    def test_signature_computed_with_wrong_token_is_rejected(self, client):
        r = _post_inbound(client, {"From": "whatsapp:+15551234567", "Body": "Hi", "MessageSid": "SM123"},
                          token="not-the-real-token")
        assert r.status_code == 403

    def test_not_configured_is_rejected(self, client):
        get_settings().TWILIO_AUTH_TOKEN = None
        try:
            r = _post_inbound(client, {"From": "whatsapp:+15551234567", "Body": "Hi", "MessageSid": "SM123"})
            assert r.status_code == 403
        finally:
            get_settings().TWILIO_AUTH_TOKEN = _AUTH_TOKEN


class TestWhatsAppIntake:
    def test_reply_from_a_known_number_logs_a_communication_and_strips_prefix(self, client, admin_headers):
        number = _whatsapp_number()
        lead = client.post("/api/v1/leads",
                          json={"company_name": "Meridian Health", "last_name": "Rao",
                                "contact_email": f"{uuid.uuid4().hex[:8]}@meridianhealth.example",
                                "whatsapp_number": number},
                          headers=admin_headers).json()

        sid = f"SM{uuid.uuid4().hex}"
        r = _post_inbound(client, {"From": f"whatsapp:{number}", "To": "whatsapp:+15550001111",
                                   "Body": "Sounds good, call me.", "MessageSid": sid})
        assert r.status_code == 200, r.text
        result = r.json()
        assert result["matched_lead"] is True
        assert result["lead_id"] == lead["id"]
        assert result["duplicate"] is False

        comms = client.get(f"/api/v1/leads/{lead['id']}/communications", headers=admin_headers).json()
        inbound = next(c for c in comms if c["direction"] == "INBOUND")
        assert inbound["channel"] == "WHATSAPP"
        assert inbound["body"] == "Sounds good, call me."
        assert inbound["provider_message_id"] == sid
        # "whatsapp:" must never reach from_address (or Lead.whatsapp_number).
        assert inbound["from_address"] == number
        assert inbound["id"] == result["communication_id"]

    def test_inbound_message_refreshes_the_24h_window(self, client, admin_headers):
        number = _whatsapp_number()
        lead = client.post("/api/v1/leads",
                          json={"company_name": "Meridian Health", "last_name": "Rao",
                                "contact_email": f"{uuid.uuid4().hex[:8]}@meridianhealth.example",
                                "whatsapp_number": number},
                          headers=admin_headers).json()
        assert lead["whatsapp_window_expires_at"] is None

        _post_inbound(client, {"From": f"whatsapp:{number}", "Body": "Hi", "MessageSid": f"SM{uuid.uuid4().hex}"})

        refreshed = client.get(f"/api/v1/leads/{lead['id']}", headers=admin_headers).json()
        assert refreshed["whatsapp_window_expires_at"] is not None

    def test_reply_from_an_unknown_number_is_not_logged_against_any_lead(self, client):
        number = _whatsapp_number()
        r = _post_inbound(client, {"From": f"whatsapp:{number}", "Body": "Who is this?",
                                   "MessageSid": f"SM{uuid.uuid4().hex}"})
        assert r.status_code == 200, r.text
        result = r.json()
        assert result["matched_lead"] is False
        assert result["lead_id"] is None
        assert result["communication_id"] is None

    def test_duplicate_message_sid_is_not_re_ingested(self, client, admin_headers):
        """Simulates Twilio retrying the same webhook call (e.g. a slow
        response) — must not create a second INBOUND Communication."""
        number = _whatsapp_number()
        lead = client.post("/api/v1/leads",
                          json={"company_name": "Meridian Health", "last_name": "Rao",
                                "contact_email": f"{uuid.uuid4().hex[:8]}@meridianhealth.example",
                                "whatsapp_number": number},
                          headers=admin_headers).json()
        sid = f"SM{uuid.uuid4().hex}"

        r = _post_inbound(client, {"From": f"whatsapp:{number}", "Body": "First", "MessageSid": sid})
        assert r.status_code == 200, r.text
        assert r.json()["duplicate"] is False

        r = _post_inbound(client, {"From": f"whatsapp:{number}", "Body": "First", "MessageSid": sid})
        assert r.status_code == 200, r.text
        assert r.json()["duplicate"] is True

        comms = client.get(f"/api/v1/leads/{lead['id']}/communications", headers=admin_headers).json()
        assert sum(1 for c in comms if c["direction"] == "INBOUND") == 1


class TestWhatsAppStatusCallback:
    def test_updates_delivery_status_by_provider_message_id(self, client, admin_headers):
        from src.integrations.twilio_whatsapp import get_whatsapp_sender
        from src.server import app

        class _FakeSender:
            def send(self, to_number, body):
                return sid

        number = _whatsapp_number()
        lead = client.post("/api/v1/leads",
                          json={"company_name": "Meridian Health", "last_name": "Rao",
                                "contact_email": f"{uuid.uuid4().hex[:8]}@meridianhealth.example",
                                "whatsapp_number": number},
                          headers=admin_headers).json()

        sid = f"SM{uuid.uuid4().hex}"
        app.dependency_overrides[get_whatsapp_sender] = lambda: _FakeSender()
        try:
            r = client.post(f"/api/v1/leads/{lead['id']}/whatsapp", json={"body": "Hi"}, headers=admin_headers)
            assert r.status_code == 201, r.text
        finally:
            app.dependency_overrides.pop(get_whatsapp_sender, None)

        r = _post_status(client, {"MessageSid": sid, "MessageStatus": "delivered"})
        assert r.status_code == 200, r.text

        comms = client.get(f"/api/v1/leads/{lead['id']}/communications", headers=admin_headers).json()
        outbound = next(c for c in comms if c["direction"] == "OUTBOUND")
        assert outbound["delivery_status"] == "delivered"

    def test_failed_status_records_error_code(self, client, admin_headers):
        from src.integrations.twilio_whatsapp import get_whatsapp_sender
        from src.server import app

        sid = f"SM{uuid.uuid4().hex}"

        class _FakeSender:
            def send(self, to_number, body):
                return sid

        number = _whatsapp_number()
        lead = client.post("/api/v1/leads",
                          json={"company_name": "Meridian Health", "last_name": "Rao",
                                "contact_email": f"{uuid.uuid4().hex[:8]}@meridianhealth.example",
                                "whatsapp_number": number},
                          headers=admin_headers).json()

        app.dependency_overrides[get_whatsapp_sender] = lambda: _FakeSender()
        try:
            client.post(f"/api/v1/leads/{lead['id']}/whatsapp", json={"body": "Hi"}, headers=admin_headers)
        finally:
            app.dependency_overrides.pop(get_whatsapp_sender, None)

        r = _post_status(client, {"MessageSid": sid, "MessageStatus": "failed", "ErrorCode": "63016"})
        assert r.status_code == 200, r.text

        comms = client.get(f"/api/v1/leads/{lead['id']}/communications", headers=admin_headers).json()
        outbound = next(c for c in comms if c["direction"] == "OUTBOUND")
        assert outbound["delivery_status"] == "failed"
        assert outbound["failure_code"] == "63016"

    def test_unknown_sid_is_a_silent_noop(self, client):
        r = _post_status(client, {"MessageSid": f"SM{uuid.uuid4().hex}", "MessageStatus": "delivered"})
        assert r.status_code == 200
