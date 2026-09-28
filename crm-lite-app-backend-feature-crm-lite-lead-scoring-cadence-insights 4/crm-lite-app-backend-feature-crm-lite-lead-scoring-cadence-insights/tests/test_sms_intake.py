"""Inbound SMS-to-lead (POST /sms-intake/webhook) — one Twilio webhook call
per inbound text, matched against Lead.contact_phone/mobile_phone. Unlike
inbound email, an unmatched sender does NOT get a new Lead auto-created (see
crm_service.process_inbound_sms()'s docstring for why: Lead.contact_email is
required and an SMS reply carries no email address).

Every test signs its own request exactly the way Twilio actually would
(independently of utils.security._twilio_signature, so this isn't a
tautological test of the same code it's meant to check), and sets
TWILIO_AUTH_TOKEN explicitly rather than relying on the ambient environment.

Phone numbers are uuid-suffixed throughout — this test DB has no per-test
rollback (a persistent shared Postgres, see conftest.py), so a fixed literal
number would collide with a lead a prior run already left behind.
"""
import base64
import hashlib
import hmac
import uuid

from src.config.config_reader import get_settings

_AUTH_TOKEN = "test-twilio-auth-token"
_WEBHOOK_URL = "http://testserver/api/v1/sms-intake/webhook"


def _phone() -> str:
    # Not a real E.164 number, but unique and stable enough to round-trip
    # through Lead.contact_phone / the webhook's From field for a test.
    return f"+1555{uuid.uuid4().int % 10_000_000:07d}"


def _sign(url: str, params: dict[str, str], token: str) -> str:
    data = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    digest = hmac.new(token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


def _post(client, params: dict[str, str], *, token: str = _AUTH_TOKEN, signature: str | None = None):
    sig = signature if signature is not None else _sign(_WEBHOOK_URL, params, token)
    return client.post("/api/v1/sms-intake/webhook", data=params, headers={"X-Twilio-Signature": sig})


def setup_module():
    settings = get_settings()
    settings.TWILIO_AUTH_TOKEN = _AUTH_TOKEN
    # Cleared explicitly — an ambient TWILIO_PUBLIC_BASE_URL (e.g. from a
    # real .env) would make require_twilio_signature reconstruct the signed
    # URL from it instead of request.url, breaking every test below that
    # signs against _WEBHOOK_URL. TestPublicBaseUrlSignature below sets its
    # own value for the tests that specifically exercise that path.
    settings.TWILIO_PUBLIC_BASE_URL = None


def teardown_module():
    settings = get_settings()
    settings.TWILIO_AUTH_TOKEN = None
    settings.TWILIO_PUBLIC_BASE_URL = None


class TestSignatureAuth:
    def test_missing_signature_is_rejected(self, client):
        r = client.post("/api/v1/sms-intake/webhook", data={"From": "+15551234567", "Body": "Hi"})
        assert r.status_code == 401

    def test_wrong_signature_is_rejected(self, client):
        r = _post(client, {"From": "+15551234567", "Body": "Hi", "MessageSid": "SM123"}, signature="bogus")
        assert r.status_code == 401

    def test_signature_computed_with_wrong_token_is_rejected(self, client):
        r = _post(client, {"From": "+15551234567", "Body": "Hi", "MessageSid": "SM123"}, token="not-the-real-token")
        assert r.status_code == 401

    def test_not_configured_is_rejected(self, client):
        get_settings().TWILIO_AUTH_TOKEN = None
        try:
            r = _post(client, {"From": "+15551234567", "Body": "Hi", "MessageSid": "SM123"})
            assert r.status_code == 401
        finally:
            get_settings().TWILIO_AUTH_TOKEN = _AUTH_TOKEN


class TestSmsIntake:
    def test_reply_from_a_known_number_logs_a_communication(self, client, admin_headers):
        phone = _phone()
        lead = client.post("/api/v1/leads",
                          json={"company_name": "Meridian Health", "last_name": "Rao",
                                "contact_email": f"{uuid.uuid4().hex[:8]}@meridianhealth.example",
                                "contact_phone": phone},
                          headers=admin_headers).json()

        sid = f"SM{uuid.uuid4().hex}"
        r = _post(client, {"From": phone, "To": "+15550001111", "Body": "Sounds good, call me.",
                           "MessageSid": sid})
        assert r.status_code == 200, r.text
        result = r.json()
        assert result["matched_lead"] is True
        assert result["lead_id"] == lead["id"]
        assert result["duplicate"] is False

        comms = client.get(f"/api/v1/leads/{lead['id']}/communications", headers=admin_headers).json()
        inbound = next(c for c in comms if c["direction"] == "INBOUND")
        assert inbound["channel"] == "SMS"
        assert inbound["body"] == "Sounds good, call me."
        assert inbound["provider_message_id"] == sid
        assert inbound["from_address"] == phone
        assert inbound["id"] == result["communication_id"]

    def test_reply_from_a_number_only_on_mobile_phone_matches(self, client, admin_headers):
        phone = _phone()
        lead = client.post("/api/v1/leads",
                          json={"company_name": "Meridian Health", "last_name": "Rao",
                                "contact_email": f"{uuid.uuid4().hex[:8]}@meridianhealth.example",
                                "mobile_phone": phone},
                          headers=admin_headers).json()

        r = _post(client, {"From": phone, "Body": "Hi", "MessageSid": f"SM{uuid.uuid4().hex}"})
        assert r.status_code == 200, r.text
        assert r.json()["matched_lead"] is True
        assert r.json()["lead_id"] == lead["id"]

    def test_reply_from_an_unknown_number_is_not_logged_against_any_lead(self, client):
        phone = _phone()
        r = _post(client, {"From": phone, "Body": "Who is this?", "MessageSid": f"SM{uuid.uuid4().hex}"})
        assert r.status_code == 200, r.text
        result = r.json()
        assert result["matched_lead"] is False
        assert result["lead_id"] is None
        assert result["communication_id"] is None

    def test_duplicate_message_sid_is_not_re_ingested(self, client, admin_headers):
        """Simulates Twilio retrying the same webhook call (e.g. a slow
        response) — must not create a second INBOUND Communication."""
        phone = _phone()
        lead = client.post("/api/v1/leads",
                          json={"company_name": "Meridian Health", "last_name": "Rao",
                                "contact_email": f"{uuid.uuid4().hex[:8]}@meridianhealth.example",
                                "contact_phone": phone},
                          headers=admin_headers).json()
        sid = f"SM{uuid.uuid4().hex}"

        r = _post(client, {"From": phone, "Body": "First", "MessageSid": sid})
        assert r.status_code == 200, r.text
        assert r.json()["duplicate"] is False

        r = _post(client, {"From": phone, "Body": "First", "MessageSid": sid})
        assert r.status_code == 200, r.text
        assert r.json()["duplicate"] is True

        comms = client.get(f"/api/v1/leads/{lead['id']}/communications", headers=admin_headers).json()
        assert sum(1 for c in comms if c["direction"] == "INBOUND") == 1


class TestPublicBaseUrlSignature:
    """TWILIO_PUBLIC_BASE_URL reconstruction — mirrors the hardening
    test_whatsapp_intake.py already exercises for
    require_twilio_whatsapp_signature, now applied to require_twilio_signature
    too: behind the gateway, request.url reflects whatever scheme/host the
    gateway's own outbound hop used, not necessarily the https://<public
    host> URL Twilio actually signed (see security.py's Cloud Run note)."""

    _PUBLIC_BASE_URL = "https://public.example.com"
    _PUBLIC_WEBHOOK_URL = f"{_PUBLIC_BASE_URL}/api/v1/sms-intake/webhook"

    def setup_method(self):
        get_settings().TWILIO_PUBLIC_BASE_URL = self._PUBLIC_BASE_URL

    def teardown_method(self):
        get_settings().TWILIO_PUBLIC_BASE_URL = None

    def test_signature_computed_against_public_base_url_is_accepted(self, client):
        params = {"From": "+15551234567", "Body": "Hi", "MessageSid": f"SM{uuid.uuid4().hex}"}
        sig = _sign(self._PUBLIC_WEBHOOK_URL, params, _AUTH_TOKEN)
        r = client.post("/api/v1/sms-intake/webhook", data=params, headers={"X-Twilio-Signature": sig})
        assert r.status_code == 200, r.text

    def test_signature_computed_against_raw_request_url_is_rejected(self, client):
        """Must validate against TWILIO_PUBLIC_BASE_URL, not request.url as
        Starlette sees it (which behind the gateway could be an internal
        http:// URL Twilio never actually signed)."""
        params = {"From": "+15551234567", "Body": "Hi", "MessageSid": f"SM{uuid.uuid4().hex}"}
        wrong_url_sig = _sign(_WEBHOOK_URL, params, _AUTH_TOKEN)
        r = client.post("/api/v1/sms-intake/webhook", data=params, headers={"X-Twilio-Signature": wrong_url_sig})
        assert r.status_code == 401
