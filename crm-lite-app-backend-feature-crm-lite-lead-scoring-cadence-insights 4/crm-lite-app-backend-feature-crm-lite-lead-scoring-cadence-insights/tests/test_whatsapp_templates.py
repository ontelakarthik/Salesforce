"""WhatsApp Content Template support in services/whatsapp_service.py —
template sends (the only thing WhatsApp allows outside a lead's 24-hour
customer-service window), the WHATSAPP_TEMPLATE_REQUIRED rewrap of a
rejected free-form send, and syncing the template catalogue from Twilio.

Service-level with in-memory fake repositories rather than through the
HTTP routes (tests/test_whatsapp_sending.py covers those against the real
Postgres test DB), so these run without a database. The acting user holds
records.see_all, which short-circuits require_lead_scope before any
org-wide-default lookup, and a non-UUID employee_id, which
verified_employee_uuid() resolves to None without an Employee lookup.
"""
import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.integrations.twilio_whatsapp import FetchedTemplate
from src.models.activity_models import SendWhatsAppRequest
from src.services import whatsapp_service
from src.utils.exceptions import DomainError
from src.utils.security import CurrentUser

_USER = CurrentUser(employee_id="test-admin", capabilities={"records.see_all"})
_COMMUNICATION_FIELDS = (
    "account_id", "agreement_id", "lead_id", "received_via_team_id", "direction", "channel", "subject",
    "body", "notes", "from_address", "to_recipients", "cc_recipients", "graph_message_id",
    "provider_message_id", "occurred_at", "source", "call_duration_seconds", "call_disposition_id",
    "opened_at", "replied_at", "delivery_status", "failure_code", "whatsapp_template_id",
    "template_variables", "media_url", "media_content_type", "logged_by_employee_id",
    "created_at", "updated_at", "created_by", "updated_by",
)


@pytest.fixture(autouse=True)
def _no_disposition_lookup(monkeypatch):
    # _communication_out() otherwise reads the call_disposition table.
    monkeypatch.setattr("src.services.activity_service._call_disposition_code_map", lambda: {})


class _FakeLeadRepo:
    def __init__(self, lead):
        self.lead = lead

    def get(self, lid):
        return self.lead if lid == self.lead.id else None


class _FakeCommRepo:
    def __init__(self):
        self.rows = []

    def create(self, **fields):
        row = SimpleNamespace(**({f: None for f in _COMMUNICATION_FIELDS} | fields), id=uuid.uuid4())
        self.rows.append(row)
        return row


class _FakeTemplateRepo:
    def __init__(self, *templates):
        self.rows = {t.id: t for t in templates}

    def get(self, id_):
        return self.rows.get(id_)

    def list(self):
        return list(self.rows.values())

    def list_approved_active(self):
        return [t for t in self.rows.values() if t.approval_status == "APPROVED" and t.is_active]

    def create(self, **fields):
        row = _template(**fields)
        self.rows[row.id] = row
        return row

    def update(self, id_, **fields):
        row = self.rows[id_]
        for k, v in fields.items():
            setattr(row, k, v)
        return row


class _FakeSender:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.sent = []
        self.sent_templates = []

    def send(self, to_number, body):
        if self.fail:
            raise DomainError("WHATSAPP_SEND_FAILED", "Twilio rejected the message: ContentSid Required", 502)
        self.sent.append((to_number, body))
        return f"SM{uuid.uuid4().hex}"

    def send_template(self, to_number, content_sid, variables):
        self.sent_templates.append((to_number, content_sid, variables))
        return f"SM{uuid.uuid4().hex}"


def _lead(window_expires_at=None):
    return SimpleNamespace(id=uuid.uuid4(), whatsapp_number="+917330671971", contact_phone=None,
                           mobile_phone=None, whatsapp_window_expires_at=window_expires_at)


def _template(**overrides):
    now = datetime.now(timezone.utc)
    fields = {"id": uuid.uuid4(), "name": "sample_issue_resolution", "content_sid": "HX111", "language": "en",
              "category": "UTILITY", "body_preview": "Hi {{1}}, your ticket {{2}} is resolved.",
              "variable_count": 2, "approval_status": "APPROVED", "is_active": True,
              "created_at": now, "updated_at": now, "created_by": "seed", "updated_by": "seed"}
    return SimpleNamespace(**(fields | overrides))


def _send(lead, templates, sender, **payload):
    comm_repo = _FakeCommRepo()
    out = whatsapp_service.send_lead_whatsapp(
        _USER, _FakeLeadRepo(lead), comm_repo, templates, sender, lead.id, SendWhatsAppRequest(**payload))
    return out, comm_repo


class TestTemplateSend:
    def test_sends_content_sid_and_logs_rendered_body(self):
        template, sender, lead = _template(), _FakeSender(), _lead()
        out, comm_repo = _send(lead, _FakeTemplateRepo(template), sender,
                               template_id=template.id, template_variables={"1": "Akhilesh", "2": "#4521"})

        assert sender.sent_templates == [("+917330671971", "HX111", {"1": "Akhilesh", "2": "#4521"})]
        assert sender.sent == []
        assert out.body == "Hi Akhilesh, your ticket #4521 is resolved."
        assert out.whatsapp_template_id == template.id
        assert json.loads(out.template_variables) == {"1": "Akhilesh", "2": "#4521"}
        assert out.channel == "WHATSAPP" and out.direction == "OUTBOUND"
        assert len(comm_repo.rows) == 1

    def test_template_with_no_variables(self):
        template = _template(body_preview="Thanks for reaching out!", variable_count=0)
        out, _ = _send(_lead(), _FakeTemplateRepo(template), _FakeSender(), template_id=template.id)
        assert out.body == "Thanks for reaching out!"
        assert out.template_variables is None

    @pytest.mark.parametrize("overrides", [{"approval_status": "PENDING"}, {"approval_status": "REJECTED"},
                                           {"is_active": False}])
    def test_unapproved_or_inactive_template_is_422_before_any_send(self, overrides):
        template, sender = _template(**overrides), _FakeSender()
        with pytest.raises(DomainError) as exc:
            _send(_lead(), _FakeTemplateRepo(template), sender,
                  template_id=template.id, template_variables={"1": "a", "2": "b"})
        assert exc.value.code == "WHATSAPP_TEMPLATE_NOT_SENDABLE"
        assert sender.sent_templates == []

    def test_unknown_template_is_404(self):
        with pytest.raises(DomainError) as exc:
            _send(_lead(), _FakeTemplateRepo(), _FakeSender(), template_id=uuid.uuid4())
        assert exc.value.status_code == 404

    @pytest.mark.parametrize("variables", [{"1": "a"}, {"1": "a", "2": "b", "3": "c"}, {"1": "a", "2": "  "}])
    def test_missing_extra_or_blank_variables_are_422(self, variables):
        template, sender = _template(), _FakeSender()
        with pytest.raises(DomainError) as exc:
            _send(_lead(), _FakeTemplateRepo(template), sender, template_id=template.id, template_variables=variables)
        assert exc.value.code == "WHATSAPP_TEMPLATE_VARIABLES_INVALID"
        assert sender.sent_templates == []


class TestFreeFormWindow:
    def test_rejected_free_form_outside_window_becomes_template_required(self):
        comm_repo = _FakeCommRepo()
        lead = _lead(window_expires_at=None)
        with pytest.raises(DomainError) as exc:
            whatsapp_service.send_lead_whatsapp(
                _USER, _FakeLeadRepo(lead), comm_repo, _FakeTemplateRepo(), _FakeSender(fail=True), lead.id,
                SendWhatsAppRequest(body="sample_issue_resolution"))
        assert exc.value.code == "WHATSAPP_TEMPLATE_REQUIRED"
        assert exc.value.status_code == 422
        assert "ContentSid Required" in exc.value.message
        assert comm_repo.rows == []

    def test_rejected_free_form_inside_window_keeps_twilio_error(self):
        lead = _lead(window_expires_at=datetime.now(timezone.utc) + timedelta(hours=3))
        with pytest.raises(DomainError) as exc:
            _send(lead, _FakeTemplateRepo(), _FakeSender(fail=True), body="Hi")
        assert exc.value.code == "WHATSAPP_SEND_FAILED"

    def test_spaced_number_on_an_existing_lead_is_sent_normalized(self):
        lead, sender = _lead(), _FakeSender()
        lead.whatsapp_number = "+91 7330671971"  # stored before Lead-save normalization existed
        out, _ = _send(lead, _FakeTemplateRepo(), sender, body="Hi")
        assert sender.sent == [("+917330671971", "Hi")]
        assert out.to_recipients == "+917330671971"

    def test_free_form_is_still_attempted_when_window_looks_closed(self):
        sender = _FakeSender()
        out, _ = _send(_lead(window_expires_at=None), _FakeTemplateRepo(), sender, body="Hi")
        assert sender.sent == [("+917330671971", "Hi")]
        assert out.body == "Hi" and out.whatsapp_template_id is None


class TestRequestValidation:
    @pytest.mark.parametrize("payload", [{}, {"body": "Hi", "template_id": str(uuid.uuid4())},
                                         {"body": "Hi", "template_variables": {"1": "a"}}])
    def test_needs_exactly_one_of_body_or_template(self, payload):
        with pytest.raises(ValueError):
            SendWhatsAppRequest(**payload)


class _FakeSource:
    def __init__(self, *templates):
        self.templates = list(templates)

    def fetch_templates(self):
        return self.templates


def _fetched(**overrides):
    fields = {"content_sid": "HX111", "name": "sample_issue_resolution", "language": "en", "category": "UTILITY",
              "body_preview": "Hi {{1}}", "variable_count": 1, "approval_status": "APPROVED"}
    return FetchedTemplate(**(fields | overrides))


class TestSync:
    def test_creates_new_templates(self):
        repo = _FakeTemplateRepo()
        out = whatsapp_service.sync_whatsapp_templates(
            _USER, repo, _FakeSource(_fetched(), _fetched(content_sid="HX222", name="a_pending",
                                                          approval_status="PENDING")))
        assert [(t.name, t.approval_status) for t in out] == [("a_pending", "PENDING"),
                                                              ("sample_issue_resolution", "APPROVED")]
        assert [t.content_sid for t in whatsapp_service.list_whatsapp_templates(repo)] == ["HX111"]

    def test_updates_existing_and_deactivates_vanished(self):
        kept = _template(content_sid="HX111", approval_status="PENDING", body_preview="old")
        vanished = _template(content_sid="HX999", name="deleted_on_twilio")
        repo = _FakeTemplateRepo(kept, vanished)

        whatsapp_service.sync_whatsapp_templates(_USER, repo, _FakeSource(_fetched(content_sid="HX111")))

        assert kept.approval_status == "APPROVED" and kept.body_preview == "Hi {{1}}"
        assert kept.updated_by == "test-admin"
        assert vanished.is_active is False
        assert len(repo.rows) == 2  # deactivated, never deleted
