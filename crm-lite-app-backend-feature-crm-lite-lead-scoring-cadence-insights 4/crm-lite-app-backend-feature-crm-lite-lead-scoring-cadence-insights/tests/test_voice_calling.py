"""Dial Pad browser calling — GET /leads/{id}/voice-token,
POST /voice/webhook/connect, POST /voice/webhook/status, and
POST /leads/{id}/communications/{id}/call-notes. Mirrors
tests/test_whatsapp_intake.py's shape (independent signature computation,
settings set directly on the singleton rather than via env, uuid-suffixed
test data against this suite's persistent, non-rolled-back Postgres
instance).

SMS, WhatsApp and Voice share one Twilio account (TWILIO_ACCOUNT_SID/
TWILIO_AUTH_TOKEN) by this deployment's choice — only
TWILIO_VOICE_PUBLIC_BASE_URL/TWILIO_VOICE_CALLER_ID remain Voice-specific
(a separate TwiML App/URL and caller-id number, not a separate account).

One real call = one Communication row throughout: the connect webhook
creates it (idempotent on the parent Call SID), the status webhook only
ever updates that same row, never creates a second one.
"""
import base64
import hashlib
import hmac
import uuid

from src.config.config_reader import get_settings

_AUTH_TOKEN = "test-twilio-voice-auth-token"
_PUBLIC_BASE_URL = "https://public.example.com"
_CONNECT_URL = f"{_PUBLIC_BASE_URL}/api/v1/voice/webhook/connect"
_STATUS_URL = f"{_PUBLIC_BASE_URL}/api/v1/voice/webhook/status"


def _sign(url: str, params: dict[str, str], token: str) -> str:
    data = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    digest = hmac.new(token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


def _post_connect(client, params: dict[str, str], *, token: str = _AUTH_TOKEN, signature: str | None = None):
    sig = signature if signature is not None else _sign(_CONNECT_URL, params, token)
    return client.post("/api/v1/voice/webhook/connect", data=params, headers={"X-Twilio-Signature": sig})


def _post_status(client, params: dict[str, str], *, token: str = _AUTH_TOKEN, signature: str | None = None):
    sig = signature if signature is not None else _sign(_STATUS_URL, params, token)
    return client.post("/api/v1/voice/webhook/status", data=params, headers={"X-Twilio-Signature": sig})


def setup_module():
    settings = get_settings()
    settings.TWILIO_AUTH_TOKEN = _AUTH_TOKEN
    settings.TWILIO_VOICE_PUBLIC_BASE_URL = _PUBLIC_BASE_URL
    settings.TWILIO_VOICE_CALLER_ID = "+17370000000"


def teardown_module():
    settings = get_settings()
    settings.TWILIO_AUTH_TOKEN = None
    settings.TWILIO_VOICE_PUBLIC_BASE_URL = None
    settings.TWILIO_VOICE_CALLER_ID = None


def _lead(client, headers, **overrides):
    payload = {"company_name": "Meridian Health", "contact_email": f"{uuid.uuid4().hex[:8]}@meridianhealth.example",
              "first_name": "Ananya", "last_name": "Rao"} | overrides
    r = client.post("/api/v1/leads", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


class TestVoiceTokenEndpoint:
    # No "missing bearer token -> 401" test here: conftest.py sets
    # DEV_AUTH_BYPASS=true for the whole test session (a no-token request
    # is granted a synthetic ADMIN identity, not rejected) — same reason no
    # other test file in this suite tests that path. Permission enforcement
    # is proven below via a real, minted-but-unauthorized token instead.

    def test_sales_cannot_get_token_for_unowned_lead(self, client, admin_headers, sales_headers):
        lead = _lead(client, admin_headers)  # owner unset
        r = client.get(f"/api/v1/leads/{lead['id']}/voice-token", headers=sales_headers)
        assert r.status_code == 403

    def test_503_when_not_configured(self, client, admin_headers):
        settings = get_settings()
        original = (settings.TWILIO_ACCOUNT_SID, settings.TWILIO_VOICE_API_KEY_SID,
                   settings.TWILIO_VOICE_API_KEY_SECRET, settings.TWILIO_VOICE_TWIML_APP_SID)
        settings.TWILIO_ACCOUNT_SID = None
        settings.TWILIO_VOICE_API_KEY_SID = None
        settings.TWILIO_VOICE_API_KEY_SECRET = None
        settings.TWILIO_VOICE_TWIML_APP_SID = None
        try:
            lead = _lead(client, admin_headers)
            r = client.get(f"/api/v1/leads/{lead['id']}/voice-token", headers=admin_headers)
            assert r.status_code == 503
            assert r.json()["error"]["code"] == "VOICE_PROVIDER_NOT_CONFIGURED"
        finally:
            (settings.TWILIO_ACCOUNT_SID, settings.TWILIO_VOICE_API_KEY_SID,
             settings.TWILIO_VOICE_API_KEY_SECRET, settings.TWILIO_VOICE_TWIML_APP_SID) = original

    def test_returns_a_token_when_configured(self, client, admin_headers):
        settings = get_settings()
        original_account_sid = settings.TWILIO_ACCOUNT_SID
        settings.TWILIO_ACCOUNT_SID = settings.TWILIO_ACCOUNT_SID or "AC1234567890"
        settings.TWILIO_VOICE_API_KEY_SID = "SKvoice123"
        settings.TWILIO_VOICE_API_KEY_SECRET = "supersecretkeysupersecretkey"
        settings.TWILIO_VOICE_TWIML_APP_SID = "APvoice123"
        try:
            lead = _lead(client, admin_headers)
            r = client.get(f"/api/v1/leads/{lead['id']}/voice-token", headers=admin_headers)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["token"]
            assert body["identity"]
        finally:
            settings.TWILIO_ACCOUNT_SID = original_account_sid
            settings.TWILIO_VOICE_API_KEY_SID = None
            settings.TWILIO_VOICE_API_KEY_SECRET = None
            settings.TWILIO_VOICE_TWIML_APP_SID = None


class TestSignatureAuth:
    def test_missing_signature_is_rejected(self, client):
        r = client.post("/api/v1/voice/webhook/connect", data={"CallSid": "CA1", "From": "client:x", "To": "+1"})
        assert r.status_code == 403

    def test_wrong_signature_is_rejected(self, client):
        r = _post_connect(client, {"CallSid": "CA1", "From": "client:x", "To": "+1"}, signature="bogus")
        assert r.status_code == 403

    def test_signature_computed_against_raw_request_url_is_rejected(self, client):
        params = {"CallSid": "CA1", "From": "client:x", "To": "+1"}
        wrong_url_sig = _sign("http://testserver/api/v1/voice/webhook/connect", params, _AUTH_TOKEN)
        r = _post_connect(client, params, signature=wrong_url_sig)
        assert r.status_code == 403


class TestConnectWebhook:
    def test_creates_one_communication_row_and_returns_dial_twiml(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        call_sid = f"CA{uuid.uuid4().hex}"

        r = _post_connect(client, {"CallSid": call_sid, "From": "client:employee-1",
                                   "To": "+15551234567", "LeadId": lead["id"]})
        assert r.status_code == 200, r.text
        assert "<Dial" in r.text
        assert "+15551234567</Number>" in r.text

        comms = client.get(f"/api/v1/leads/{lead['id']}/communications", headers=admin_headers).json()
        call_row = next(c for c in comms if c["channel"] == "CALL")
        assert call_row["direction"] == "OUTBOUND"
        assert call_row["provider_message_id"] == call_sid
        assert call_row["to_recipients"] == "+15551234567"
        assert call_row["delivery_status"] == "initiated"

    def test_retrying_the_same_call_sid_does_not_create_a_second_row(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        call_sid = f"CA{uuid.uuid4().hex}"
        params = {"CallSid": call_sid, "From": "client:x", "To": "+15551234567", "LeadId": lead["id"]}

        r1 = _post_connect(client, params)
        assert r1.status_code == 200
        r2 = _post_connect(client, params)
        assert r2.status_code == 200

        comms = client.get(f"/api/v1/leads/{lead['id']}/communications", headers=admin_headers).json()
        assert sum(1 for c in comms if c["provider_message_id"] == call_sid) == 1


class TestStatusWebhook:
    def test_updates_delivery_status_disposition_and_duration_on_completion(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        call_sid = f"CA{uuid.uuid4().hex}"
        _post_connect(client, {"CallSid": call_sid, "From": "client:x", "To": "+15551234567", "LeadId": lead["id"]})

        r = _post_status(client, {"CallSid": f"CAchild{uuid.uuid4().hex}", "ParentCallSid": call_sid,
                                  "CallStatus": "completed", "CallDuration": "142"})
        assert r.status_code == 200, r.text

        comms = client.get(f"/api/v1/leads/{lead['id']}/communications", headers=admin_headers).json()
        row = next(c for c in comms if c["provider_message_id"] == call_sid)
        assert row["delivery_status"] == "completed"
        assert row["call_outcome"] == "CONNECTED"
        assert row["call_duration_seconds"] == 142

    def test_non_terminal_status_updates_delivery_status_only(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        call_sid = f"CA{uuid.uuid4().hex}"
        _post_connect(client, {"CallSid": call_sid, "From": "client:x", "To": "+15551234567", "LeadId": lead["id"]})

        _post_status(client, {"CallSid": f"CAchild{uuid.uuid4().hex}", "ParentCallSid": call_sid,
                              "CallStatus": "ringing"})

        comms = client.get(f"/api/v1/leads/{lead['id']}/communications", headers=admin_headers).json()
        row = next(c for c in comms if c["provider_message_id"] == call_sid)
        assert row["delivery_status"] == "ringing"
        assert row["call_outcome"] is None
        assert row["call_duration_seconds"] is None

    def test_failed_call_records_error_code(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        call_sid = f"CA{uuid.uuid4().hex}"
        _post_connect(client, {"CallSid": call_sid, "From": "client:x", "To": "+15551234567", "LeadId": lead["id"]})

        _post_status(client, {"CallSid": f"CAchild{uuid.uuid4().hex}", "ParentCallSid": call_sid,
                              "CallStatus": "failed", "ErrorCode": "21215"})

        comms = client.get(f"/api/v1/leads/{lead['id']}/communications", headers=admin_headers).json()
        row = next(c for c in comms if c["provider_message_id"] == call_sid)
        assert row["delivery_status"] == "failed"
        assert row["call_outcome"] == "OTHER"
        assert row["failure_code"] == "21215"

    def test_unknown_call_sid_is_a_silent_noop(self, client):
        r = _post_status(client, {"CallSid": "x", "ParentCallSid": f"CA{uuid.uuid4().hex}", "CallStatus": "completed"})
        assert r.status_code == 200


class TestUpdateCallNotes:
    def test_updates_subject_and_notes_on_the_same_row(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        call_sid = f"CA{uuid.uuid4().hex}"
        _post_connect(client, {"CallSid": call_sid, "From": "client:x", "To": "+15551234567", "LeadId": lead["id"]})
        comms = client.get(f"/api/v1/leads/{lead['id']}/communications", headers=admin_headers).json()
        comm_id = next(c for c in comms if c["provider_message_id"] == call_sid)["id"]

        r = client.post(f"/api/v1/leads/{lead['id']}/communications/{comm_id}/call-notes",
                        json={"subject": "Discussed renewal", "notes": "Interested, follow up Friday"},
                        headers=admin_headers)
        assert r.status_code == 200, r.text
        assert r.json()["subject"] == "Discussed renewal"
        assert r.json()["notes"] == "Interested, follow up Friday"
        assert r.json()["id"] == comm_id

    def test_rejects_a_non_call_communication(self, client, admin_headers):
        lead = _lead(client, admin_headers, contact_phone="+15551234567")
        logged = client.post(f"/api/v1/leads/{lead['id']}/communications",
                            json={"direction": "OUTBOUND", "channel": "EMAIL", "subject": "x",
                                  "occurred_at": "2026-01-01T00:00:00Z"},
                            headers=admin_headers).json()
        r = client.post(f"/api/v1/leads/{lead['id']}/communications/{logged['id']}/call-notes",
                        json={"notes": "x"}, headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "NOT_A_CALL"

    def test_sales_cannot_edit_notes_on_unowned_leads_call(self, client, admin_headers, sales_headers):
        lead = _lead(client, admin_headers)  # owner unset
        call_sid = f"CA{uuid.uuid4().hex}"
        _post_connect(client, {"CallSid": call_sid, "From": "client:x", "To": "+15551234567", "LeadId": lead["id"]})
        comms = client.get(f"/api/v1/leads/{lead['id']}/communications", headers=admin_headers).json()
        comm_id = next(c for c in comms if c["provider_message_id"] == call_sid)["id"]

        r = client.post(f"/api/v1/leads/{lead['id']}/communications/{comm_id}/call-notes",
                        json={"notes": "x"}, headers=sales_headers)
        assert r.status_code == 403
