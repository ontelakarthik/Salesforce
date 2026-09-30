"""One-time first-contact transition — activity_service.
mark_lead_as_contacted_if_first_contact(), called after a successful Email
(POST /leads/{id}/communications/send), SMS (POST /leads/{id}/sms), or Log a
Call (POST /leads/{id}/communications with channel=CALL, or a Dial Pad call
Twilio reports as "completed").

Lead.contacted is backend-only (absent from LeadOut), so it's read straight
from the repository here rather than through the API. Same persistent,
non-rolled-back Postgres as every other test module — hence uuid-suffixed
emails and SIDs.
"""
import uuid

from src.config.config_reader import get_settings
from src.repositories.crm_repository import get_lead_repository
from src.server import app
from src.services import activity_service
from src.services.email_client import get_email_sender
from src.services.sms_service import get_sms_sender
from src.utils.exceptions import DomainError
from tests.test_voice_calling import _AUTH_TOKEN, _PUBLIC_BASE_URL, _post_connect, _post_status


class _FakeEmailSender:
    def __init__(self, fail: bool = False):
        self.fail = fail

    def send(self, to_address: str, subject: str, body: str) -> None:
        if self.fail:
            raise DomainError("EMAIL_SEND_FAILED", "simulated failure", 502)


class _FakeSmsSender:
    def __init__(self, fail: bool = False):
        self.fail = fail

    def send(self, to_number: str, body: str) -> str:
        if self.fail:
            raise DomainError("SMS_SEND_FAILED", "simulated failure", 502)
        return f"SMfake{uuid.uuid4().hex}"


def _lead(client, headers):
    r = client.post("/api/v1/leads", json={
        "company_name": "Meridian Health", "contact_email": f"{uuid.uuid4().hex[:8]}@meridian.example",
        "contact_phone": "+15551234567", "first_name": "Ananya", "last_name": "Rao",
    }, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _state(lead_id) -> tuple[str, bool]:
    row = get_lead_repository().get(uuid.UUID(lead_id))
    return row.status, row.contacted


def _send_email(client, headers, lead_id):
    return client.post(f"/api/v1/leads/{lead_id}/communications/send",
                       json={"subject": "Hello", "body": "Following up"}, headers=headers)


def _send_sms(client, headers, lead_id):
    return client.post(f"/api/v1/leads/{lead_id}/sms", json={"message": "Following up"}, headers=headers)


def _log_call(client, headers, lead_id):
    return client.post(f"/api/v1/leads/{lead_id}/communications", json={
        "direction": "OUTBOUND", "channel": "CALL", "subject": "Intro call",
        "occurred_at": "2026-09-30T10:00:00Z", "call_outcome": "CONNECTED",
    }, headers=headers)


def _set_status(client, headers, lead_id, *path):
    for status in path:
        r = client.patch(f"/api/v1/leads/{lead_id}", json={"status": status}, headers=headers)
        assert r.status_code == 200, r.text


class _WithFakeSenders:
    def setup_method(self):
        app.dependency_overrides[get_email_sender] = lambda: _FakeEmailSender()
        app.dependency_overrides[get_sms_sender] = lambda: _FakeSmsSender()

    def teardown_method(self):
        app.dependency_overrides.pop(get_email_sender, None)
        app.dependency_overrides.pop(get_sms_sender, None)


class TestFirstContact(_WithFakeSenders):
    def test_new_lead_defaults_to_not_contacted(self, client, admin_headers):
        assert _state(_lead(client, admin_headers)) == ("NEW", False)

    def test_1_successful_email_marks_contacted(self, client, admin_headers):
        lid = _lead(client, admin_headers)
        assert _send_email(client, admin_headers, lid).status_code == 201
        assert _state(lid) == ("CONTACTED", True)

    def test_2_successful_sms_marks_contacted(self, client, admin_headers):
        lid = _lead(client, admin_headers)
        assert _send_sms(client, admin_headers, lid).status_code == 201
        assert _state(lid) == ("CONTACTED", True)

    def test_3_successful_log_a_call_marks_contacted(self, client, admin_headers):
        lid = _lead(client, admin_headers)
        assert _log_call(client, admin_headers, lid).status_code == 201
        assert _state(lid) == ("CONTACTED", True)

    def test_attempting_contact_also_advances(self, client, admin_headers):
        lid = _lead(client, admin_headers)
        _set_status(client, admin_headers, lid, "ATTEMPTING_CONTACT")
        assert _send_email(client, admin_headers, lid).status_code == 201
        assert _state(lid) == ("CONTACTED", True)

    def test_logging_a_non_call_activity_does_not_trigger(self, client, admin_headers):
        lid = _lead(client, admin_headers)
        r = client.post(f"/api/v1/leads/{lid}/communications", json={
            "direction": "OUTBOUND", "channel": "LINKEDIN", "subject": "Connect request",
            "occurred_at": "2026-09-30T10:00:00Z"}, headers=admin_headers)
        assert r.status_code == 201
        assert _state(lid) == ("NEW", False)


class TestFailureLeavesLeadUntouched:
    def teardown_method(self):
        app.dependency_overrides.pop(get_email_sender, None)
        app.dependency_overrides.pop(get_sms_sender, None)

    def test_4_failed_first_email_changes_nothing(self, client, admin_headers):
        app.dependency_overrides[get_email_sender] = lambda: _FakeEmailSender(fail=True)
        lid = _lead(client, admin_headers)
        assert _send_email(client, admin_headers, lid).status_code == 502
        assert _state(lid) == ("NEW", False)

    def test_failed_first_sms_changes_nothing(self, client, admin_headers):
        app.dependency_overrides[get_sms_sender] = lambda: _FakeSmsSender(fail=True)
        lid = _lead(client, admin_headers)
        assert _send_sms(client, admin_headers, lid).status_code == 502
        assert _state(lid) == ("NEW", False)

    def test_invalid_log_a_call_changes_nothing(self, client, admin_headers):
        lid = _lead(client, admin_headers)
        r = client.post(f"/api/v1/leads/{lid}/communications", json={
            "direction": "SIDEWAYS", "channel": "CALL", "occurred_at": "2026-09-30T10:00:00Z"},
            headers=admin_headers)
        assert r.status_code == 422
        assert _state(lid) == ("NEW", False)


class TestNeverRevertsOnceContacted(_WithFakeSenders):
    def test_5_already_contacted_stays_contacted(self, client, admin_headers):
        lid = _lead(client, admin_headers)
        _send_email(client, admin_headers, lid)
        assert _send_email(client, admin_headers, lid).status_code == 201
        assert _state(lid) == ("CONTACTED", True)

    def test_6_qualifying_is_not_reverted_by_email(self, client, admin_headers):
        lid = _lead(client, admin_headers)
        _send_email(client, admin_headers, lid)
        _set_status(client, admin_headers, lid, "QUALIFYING")
        assert _send_email(client, admin_headers, lid).status_code == 201
        assert _state(lid) == ("QUALIFYING", True)

    def test_7_qualified_is_not_reverted_by_sms(self, client, admin_headers):
        lid = _lead(client, admin_headers)
        _log_call(client, admin_headers, lid)
        _set_status(client, admin_headers, lid, "QUALIFYING", "QUALIFIED")
        assert _send_sms(client, admin_headers, lid).status_code == 201
        assert _state(lid) == ("QUALIFIED", True)

    def test_8_nurturing_is_not_reverted_by_log_a_call(self, client, admin_headers):
        lid = _lead(client, admin_headers)
        _send_sms(client, admin_headers, lid)
        _set_status(client, admin_headers, lid, "NURTURING")
        assert _log_call(client, admin_headers, lid).status_code == 201
        assert _state(lid) == ("NURTURING", True)

    def test_manually_advanced_lead_is_never_pulled_back(self, client, admin_headers):
        """contacted is still False here (no activity yet) — the status alone
        shows first contact already happened, so only the flag is set."""
        lid = _lead(client, admin_headers)
        _set_status(client, admin_headers, lid, "ATTEMPTING_CONTACT", "CONTACTED", "QUALIFYING")
        assert _state(lid) == ("QUALIFYING", False)
        assert _send_email(client, admin_headers, lid).status_code == 201
        assert _state(lid) == ("QUALIFYING", True)

    def test_helper_applies_only_once(self, client, admin_headers):
        lid = uuid.UUID(_lead(client, admin_headers))
        repo = get_lead_repository()
        assert activity_service.mark_lead_as_contacted_if_first_contact(repo, lid, "test") is not None
        assert activity_service.mark_lead_as_contacted_if_first_contact(repo, lid, "test") is None


class TestDialPadCall:
    """A Dial Pad call (inside the Log a Call modal) counts only once Twilio
    reports it "completed"."""

    def setup_method(self):
        settings = get_settings()
        self._original = (settings.TWILIO_AUTH_TOKEN, settings.TWILIO_VOICE_PUBLIC_BASE_URL)
        settings.TWILIO_AUTH_TOKEN = _AUTH_TOKEN
        settings.TWILIO_VOICE_PUBLIC_BASE_URL = _PUBLIC_BASE_URL

    def teardown_method(self):
        settings = get_settings()
        settings.TWILIO_AUTH_TOKEN, settings.TWILIO_VOICE_PUBLIC_BASE_URL = self._original

    def _call(self, client, lid, final_status):
        call_sid = f"CA{uuid.uuid4().hex}"
        assert _post_connect(client, {"CallSid": call_sid, "From": "client:employee-1",
                                      "To": "+15551234567", "LeadId": lid}).status_code == 200
        assert _post_status(client, {"CallSid": f"CA{uuid.uuid4().hex}", "ParentCallSid": call_sid,
                                     "CallStatus": final_status, "CallDuration": "42"}).status_code == 200

    def test_completed_call_marks_contacted(self, client, admin_headers):
        lid = _lead(client, admin_headers)
        self._call(client, lid, "completed")
        assert _state(lid) == ("CONTACTED", True)

    def test_unanswered_call_changes_nothing(self, client, admin_headers):
        lid = _lead(client, admin_headers)
        self._call(client, lid, "no-answer")
        assert _state(lid) == ("NEW", False)


class TestContactedIsBackendOnly(_WithFakeSenders):
    def test_9_contacted_never_appears_in_lead_responses(self, client, admin_headers):
        lid = _lead(client, admin_headers)
        _send_email(client, admin_headers, lid)
        one = client.get(f"/api/v1/leads/{lid}", headers=admin_headers).json()
        listed = client.get("/api/v1/leads", headers=admin_headers).json()
        assert "contacted" not in one
        assert all("contacted" not in row for row in listed)

    def test_9_contacted_cannot_be_set_through_the_api(self, client, admin_headers):
        lid = _lead(client, admin_headers)
        r = client.patch(f"/api/v1/leads/{lid}", json={"contacted": True}, headers=admin_headers)
        assert r.status_code == 200
        assert _state(lid) == ("NEW", False)
