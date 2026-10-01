"""One-time automatic NEW -> CONTACTED transition on a Lead's first
successful Email/SMS/Call (activity_service.
mark_lead_as_contacted_if_first_contact()), driven by the backend-only
Lead.contacted flag. Once contacted=True, later activities never touch the
status again — whatever the rep has moved it to stays put.

contacted is deliberately not part of LeadOut, so these tests read it
straight off the repository rather than the API response.
"""
import threading
import uuid

from src.models import crm_models
from src.repositories.activity_repository import get_communication_repository
from src.repositories.crm_repository import get_lead_repository
from src.server import app
from src.services import activity_service, voice_service
from src.services.email_client import get_email_sender
from src.services.sms_service import get_sms_sender
from src.utils.exceptions import DomainError


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
        # uuid-suffixed — provider_message_id is unique and the test DB is
        # shared across runs (see tests/test_sms_sending.py).
        return f"SMfake{uuid.uuid4().hex}"


def _lead(client, headers, *, status: str | None = None, contacted: bool | None = None) -> str:
    payload = {"company_name": "Meridian Health", "first_name": "Ananya", "last_name": "Rao",
               "contact_email": f"lead.{uuid.uuid4().hex[:10]}@example.com",
               "contact_phone": "+15551234567"}
    r = client.post("/api/v1/leads", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    lead_id = r.json()["id"]
    # Arrange "the rep already moved this lead along" state directly — the
    # manual transition rules aren't what's under test here.
    fields = {}
    if status is not None:
        fields["status"] = status
    if contacted is not None:
        fields["contacted"] = contacted
    if fields:
        get_lead_repository().update(uuid.UUID(lead_id), **fields)
    return lead_id


def _state(lead_id: str) -> tuple[str, bool]:
    row = get_lead_repository().get(uuid.UUID(lead_id))
    return row.status, row.contacted


def _send_email(client, headers, lead_id, *, fail=False):
    app.dependency_overrides[get_email_sender] = lambda: _FakeEmailSender(fail=fail)
    try:
        return client.post(f"/api/v1/leads/{lead_id}/communications/send",
                           json={"subject": "Intro", "body": "Hi there"}, headers=headers)
    finally:
        app.dependency_overrides.pop(get_email_sender, None)


def _send_sms(client, headers, lead_id, *, fail=False):
    app.dependency_overrides[get_sms_sender] = lambda: _FakeSmsSender(fail=fail)
    try:
        return client.post(f"/api/v1/leads/{lead_id}/sms", json={"message": "Hi there"}, headers=headers)
    finally:
        app.dependency_overrides.pop(get_sms_sender, None)


def _log_call(client, headers, lead_id, *, outcome="CONNECTED"):
    # Same body the frontend's "Log a call" modal sends (LeadActivityPanel.tsx).
    return client.post(f"/api/v1/leads/{lead_id}/communications", json={
        "direction": "OUTBOUND", "channel": "Call", "subject": "Call with Ananya Rao",
        "occurred_at": "2026-10-01T10:00:00Z", "call_outcome": outcome,
    }, headers=headers)


class TestFirstContactAdvancesNewLead:
    def test_1_successful_email(self, client, admin_headers):
        lead_id = _lead(client, admin_headers)
        assert _state(lead_id) == ("NEW", False)
        assert _send_email(client, admin_headers, lead_id).status_code == 201
        assert _state(lead_id) == ("CONTACTED", True)

    def test_2_successful_sms(self, client, admin_headers):
        lead_id = _lead(client, admin_headers)
        assert _send_sms(client, admin_headers, lead_id).status_code == 201
        assert _state(lead_id) == ("CONTACTED", True)

    def test_3_successful_log_a_call(self, client, admin_headers):
        lead_id = _lead(client, admin_headers)
        assert _log_call(client, admin_headers, lead_id).status_code == 201
        assert _state(lead_id) == ("CONTACTED", True)

    def test_status_change_is_visible_through_the_existing_lead_api(self, client, admin_headers):
        lead_id = _lead(client, admin_headers)
        _send_email(client, admin_headers, lead_id)
        assert client.get(f"/api/v1/leads/{lead_id}", headers=admin_headers).json()["status"] == "CONTACTED"

    def test_attempting_contact_also_advances(self, client, admin_headers):
        lead_id = _lead(client, admin_headers, status="ATTEMPTING_CONTACT")
        _send_sms(client, admin_headers, lead_id)
        assert _state(lead_id) == ("CONTACTED", True)


class TestFailedAttemptChangesNothing:
    def test_4_first_email_fails(self, client, admin_headers):
        lead_id = _lead(client, admin_headers)
        assert _send_email(client, admin_headers, lead_id, fail=True).status_code == 502
        assert _state(lead_id) == ("NEW", False)

    def test_first_sms_fails(self, client, admin_headers):
        lead_id = _lead(client, admin_headers)
        assert _send_sms(client, admin_headers, lead_id, fail=True).status_code == 502
        assert _state(lead_id) == ("NEW", False)

    def test_call_that_did_not_reach_the_lead(self, client, admin_headers):
        lead_id = _lead(client, admin_headers)
        for outcome in ("NO_ANSWER", "BUSY", "VOICEMAIL", "WRONG_NUMBER"):
            assert _log_call(client, admin_headers, lead_id, outcome=outcome).status_code == 201
        assert _state(lead_id) == ("NEW", False)

    def test_failure_then_success_still_counts_as_first_contact(self, client, admin_headers):
        lead_id = _lead(client, admin_headers)
        _send_email(client, admin_headers, lead_id, fail=True)
        _send_email(client, admin_headers, lead_id)
        assert _state(lead_id) == ("CONTACTED", True)


class TestAlreadyContactedLeadKeepsItsStatus:
    def test_5_already_contacted_email(self, client, admin_headers):
        lead_id = _lead(client, admin_headers, status="CONTACTED", contacted=True)
        _send_email(client, admin_headers, lead_id)
        assert _state(lead_id) == ("CONTACTED", True)

    def test_6_qualifying_email_does_not_revert(self, client, admin_headers):
        lead_id = _lead(client, admin_headers, status="QUALIFYING", contacted=True)
        assert _send_email(client, admin_headers, lead_id).status_code == 201
        assert _state(lead_id) == ("QUALIFYING", True)

    def test_7_qualified_sms_does_not_revert(self, client, admin_headers):
        lead_id = _lead(client, admin_headers, status="QUALIFIED", contacted=True)
        assert _send_sms(client, admin_headers, lead_id).status_code == 201
        assert _state(lead_id) == ("QUALIFIED", True)

    def test_8_nurturing_call_does_not_revert(self, client, admin_headers):
        lead_id = _lead(client, admin_headers, status="NURTURING", contacted=True)
        assert _log_call(client, admin_headers, lead_id).status_code == 201
        assert _state(lead_id) == ("NURTURING", True)

    def test_full_walkthrough_email_then_manual_qualifying_then_email(self, client, admin_headers):
        lead_id = _lead(client, admin_headers)
        _send_email(client, admin_headers, lead_id)
        assert _state(lead_id) == ("CONTACTED", True)

        r = client.patch(f"/api/v1/leads/{lead_id}", json={"status": "QUALIFYING"}, headers=admin_headers)
        assert r.status_code == 200, r.text
        assert _state(lead_id) == ("QUALIFYING", True)

        _send_email(client, admin_headers, lead_id)
        _send_sms(client, admin_headers, lead_id)
        _log_call(client, admin_headers, lead_id)
        assert _state(lead_id) == ("QUALIFYING", True)

    def test_lead_moved_forward_by_hand_is_never_pulled_back(self, client, admin_headers):
        """contacted=False but already past first contact (e.g. advanced
        manually before any logged activity) — first contact only records
        the flag; it never moves the status backwards."""
        lead_id = _lead(client, admin_headers, status="QUALIFYING", contacted=False)
        _send_email(client, admin_headers, lead_id)
        assert _state(lead_id) == ("QUALIFYING", True)


class TestDialPadCall:
    """Calls placed from the Dial Pad inside the "Log a call" modal — logged
    by the Twilio webhooks, not by POST /communications."""

    def _call_row(self, client, headers, lead_id) -> str:
        sid = f"CAfake{uuid.uuid4().hex}"
        get_communication_repository().create(
            lead_id=uuid.UUID(lead_id), account_id=None, agreement_id=None,
            direction="OUTBOUND", channel="CALL", to_recipients="+15551234567",
            occurred_at=activity_service._now(), source="VOICE_DIAL_PAD",
            provider_message_id=sid, delivery_status="initiated",
            created_by="test", updated_by="test",
        )
        return sid

    def _status(self, sid, call_status):
        voice_service.process_voice_status_callback(
            get_communication_repository(), call_sid=f"CAchild{uuid.uuid4().hex}", parent_call_sid=sid,
            call_status=call_status, call_duration="42", error_code=None,
            lead_repo=get_lead_repository())

    def test_answered_call_is_first_contact(self, client, admin_headers):
        lead_id = _lead(client, admin_headers)
        sid = self._call_row(client, admin_headers, lead_id)
        self._status(sid, "ringing")
        assert _state(lead_id) == ("NEW", False)
        self._status(sid, "completed")
        assert _state(lead_id) == ("CONTACTED", True)

    def test_unanswered_call_changes_nothing(self, client, admin_headers):
        lead_id = _lead(client, admin_headers)
        self._status(self._call_row(client, admin_headers, lead_id), "no-answer")
        assert _state(lead_id) == ("NEW", False)

    def test_answered_call_on_nurturing_lead_does_not_revert(self, client, admin_headers):
        lead_id = _lead(client, admin_headers, status="NURTURING", contacted=True)
        self._status(self._call_row(client, admin_headers, lead_id), "completed")
        assert _state(lead_id) == ("NURTURING", True)


class TestOnlyOnce:
    def test_concurrent_first_contacts_apply_exactly_once(self, client, admin_headers):
        lead_id = uuid.UUID(_lead(client, admin_headers))
        results = []

        def _hit():
            results.append(activity_service.mark_lead_as_contacted_if_first_contact(
                get_lead_repository(), lead_id, updated_by="test"))

        threads = [threading.Thread(target=_hit) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(r.contacted and r.status == "CONTACTED" for r in results)
        # Exactly one audited status/contacted change — the other 7 callers
        # found contacted already True under the row lock and applied nothing.
        audit = client.get("/api/v1/audit", params={"entity_id": str(lead_id)}, headers=admin_headers)
        assert audit.status_code == 200, audit.text
        changed = [a["field_changed"] for a in audit.json() if a["action"] == "UPDATE"]
        assert changed.count("status") == 1
        assert changed.count("contacted") == 1

    def test_helper_is_a_no_op_once_contacted(self, client, admin_headers):
        lead_id = uuid.UUID(_lead(client, admin_headers, status="QUALIFYING", contacted=True))
        row = activity_service.mark_lead_as_contacted_if_first_contact(
            get_lead_repository(), lead_id, updated_by="test")
        assert (row.status, row.contacted) == ("QUALIFYING", True)


class TestContactedIsBackendOnly:
    """TEST 9: the frontend can only render what the API returns, so
    contacted must never appear in any Lead request/response schema or
    response body, and must not be settable through the API."""

    def test_not_in_any_lead_api_schema(self):
        for schema in (crm_models.LeadCreate, crm_models.LeadUpdate, crm_models.LeadOut):
            assert "contacted" not in schema.model_fields, schema.__name__

    def test_not_in_lead_responses(self, client, admin_headers):
        lead_id = _lead(client, admin_headers)
        _send_email(client, admin_headers, lead_id)
        assert "contacted" not in client.get(f"/api/v1/leads/{lead_id}", headers=admin_headers).json()
        listed = client.get("/api/v1/leads", headers=admin_headers).json()
        assert all("contacted" not in row for row in listed)

    def test_cannot_be_set_through_the_api(self, client, admin_headers):
        lead_id = _lead(client, admin_headers)
        client.patch(f"/api/v1/leads/{lead_id}", json={"contacted": True}, headers=admin_headers)
        assert _state(lead_id) == ("NEW", False)

    def test_not_a_field_level_security_field(self):
        from src.services.crm_service import _FLS_FIELDS
        assert all("contacted" not in fields for fields in _FLS_FIELDS.values())
