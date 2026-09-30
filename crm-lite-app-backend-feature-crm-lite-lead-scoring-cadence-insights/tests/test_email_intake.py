"""Inbound email-to-lead (POST /email-intake/poll) — a sender with no
existing Lead becomes a new one; a sender who already has one gets an
INBOUND Communication logged against it instead of a duplicate. Every test
overrides get_inbound_email_receiver with a fake so a run never attempts a
real IMAP connection, and sets the shared secret explicitly rather than
relying on the ambient environment having (or not having) one configured.

Sender addresses are uuid-suffixed throughout — this test DB has no
per-test rollback (a persistent shared Postgres, see conftest.py), so a
fixed literal address would collide with a lead a prior run already left
behind and silently flip a "new sender" case into a "known sender" one.
"""
import uuid
from datetime import datetime, timezone

from src.config.config_reader import get_settings
from src.server import app
from src.services.inbound_email_client import InboundEmail, get_inbound_email_receiver

_SECRET = "test-email-intake-secret"


def _unique(local: str, domain: str = "example.com") -> str:
    return f"{local}.{uuid.uuid4().hex[:8]}@{domain}"


class _FakeReceiver:
    def __init__(self, messages: list[InboundEmail]):
        self.messages = messages

    def fetch_unseen(self) -> list[InboundEmail]:
        return self.messages


def _msg(from_address: str, from_name: str | None = None, subject: str | None = "Hi",
        body: str | None = "Interested in your product.", message_id: str | None = None) -> InboundEmail:
    return InboundEmail(from_address=from_address, from_name=from_name, subject=subject,
                        body=body, received_at=datetime.now(timezone.utc), message_id=message_id)


def _override(messages: list[InboundEmail]):
    app.dependency_overrides[get_inbound_email_receiver] = lambda: _FakeReceiver(messages)


def setup_module():
    get_settings().EMAIL_INTAKE_SECRET = _SECRET


def teardown_module():
    get_settings().EMAIL_INTAKE_SECRET = None


class TestEmailIntakeAuth:
    def teardown_method(self):
        app.dependency_overrides.pop(get_inbound_email_receiver, None)

    def test_missing_secret_is_rejected(self, client):
        _override([])
        r = client.post("/api/v1/email-intake/poll")
        assert r.status_code == 401

    def test_wrong_secret_is_rejected(self, client):
        _override([])
        r = client.post("/api/v1/email-intake/poll", headers={"X-Email-Intake-Secret": "wrong"})
        assert r.status_code == 401


class TestEmailIntake:
    def teardown_method(self):
        app.dependency_overrides.pop(get_inbound_email_receiver, None)

    def _poll(self, client):
        return client.post("/api/v1/email-intake/poll", headers={"X-Email-Intake-Secret": _SECRET})

    def test_new_sender_becomes_an_unowned_lead(self, client, admin_headers):
        address = _unique("jordan", "newprospect.example")
        _override([_msg(address, from_name="Jordan Lee")])
        r = self._poll(client)
        assert r.status_code == 200, r.text
        result = r.json()
        assert result["messages_processed"] == 1
        assert result["leads_created"] == 1
        assert result["matched_existing_lead"] == 0
        assert result["errors"] == 0

        leads = client.get("/api/v1/leads", headers=admin_headers).json()
        created = next(row for row in leads if row["contact_email"] == address)
        assert created["first_name"] == "Jordan"
        assert created["last_name"] == "Lee"
        assert created["company_name"] == "newprospect.example"
        assert created["source"] == "EMAIL"
        assert created["owner_employee_id"] is None

        insights = client.get(f"/api/v1/leads/{created['id']}/email-insights", headers=admin_headers).json()
        assert insights["inbound_count"] == 1

    def test_sender_with_no_display_name_falls_back_to_local_part(self, client, admin_headers):
        local = f"taylor.{uuid.uuid4().hex[:8]}"
        address = f"{local}@example.com"
        _override([_msg(address)])
        self._poll(client)
        leads = client.get("/api/v1/leads", headers=admin_headers).json()
        created = next(row for row in leads if row["contact_email"] == address)
        assert created["last_name"] == local
        assert created["first_name"] is None

    def test_known_sender_logs_a_communication_instead_of_a_duplicate_lead(self, client, admin_headers):
        address = _unique("ananya", "meridianhealth.example")
        lead = client.post("/api/v1/leads",
                          json={"company_name": "Meridian Health", "first_name": "Ananya", "last_name": "Rao",
                                "contact_email": address},
                          headers=admin_headers).json()
        _override([_msg(address, subject="Following up")])

        r = self._poll(client)
        assert r.status_code == 200, r.text
        result = r.json()
        assert result["leads_created"] == 0
        assert result["matched_existing_lead"] == 1

        leads = client.get("/api/v1/leads", headers=admin_headers).json()
        assert sum(1 for row in leads if row["contact_email"] == address) == 1

        insights = client.get(f"/api/v1/leads/{lead['id']}/email-insights", headers=admin_headers).json()
        assert insights["inbound_count"] == 1

    def test_reply_from_a_new_lead_advances_it_to_contacted(self, client, admin_headers):
        address = _unique("priya", "meridianhealth.example")
        lead = client.post("/api/v1/leads",
                          json={"company_name": "Meridian Health", "first_name": "Priya", "last_name": "Rao",
                                "contact_email": address},
                          headers=admin_headers).json()
        assert lead["status"] == "NEW"
        _override([_msg(address, subject="Re: intro")])

        r = self._poll(client)
        assert r.status_code == 200, r.text
        assert r.json()["matched_existing_lead"] == 1

        updated = client.get(f"/api/v1/leads/{lead['id']}", headers=admin_headers).json()
        assert updated["status"] == "CONTACTED"

    def test_reply_from_a_qualifying_lead_does_not_change_its_status(self, client, admin_headers):
        # A reply is only a meaningful signal when the conversation hasn't
        # started yet — a lead already deep in the pipeline shouldn't get
        # yanked back to CONTACTED just because they sent another email.
        address = _unique("devika", "meridianhealth.example")
        lead = client.post("/api/v1/leads",
                          json={"company_name": "Meridian Health", "first_name": "Devika", "last_name": "Rao",
                                "contact_email": address},
                          headers=admin_headers).json()
        for status in ["ATTEMPTING_CONTACT", "CONTACTED", "QUALIFYING"]:
            r = client.patch(f"/api/v1/leads/{lead['id']}", json={"status": status}, headers=admin_headers)
            assert r.status_code == 200, r.text
        _override([_msg(address, subject="Another follow-up")])

        r = self._poll(client)
        assert r.status_code == 200, r.text

        updated = client.get(f"/api/v1/leads/{lead['id']}", headers=admin_headers).json()
        assert updated["status"] == "QUALIFYING"

    def test_duplicate_message_id_is_not_re_ingested(self, client, admin_headers):
        """Simulates a re-poll of the same message (e.g. its \\Seen flag got
        reset) — must not create a second INBOUND Communication for it."""
        address = _unique("morgan", "meridianhealth.example")
        lead = client.post("/api/v1/leads",
                          json={"company_name": "Meridian Health", "last_name": "Rao",
                                "contact_email": address},
                          headers=admin_headers).json()
        msg = _msg(address, subject="Following up", message_id=f"<{uuid.uuid4()}@sender.example>")

        _override([msg])
        r = self._poll(client)
        assert r.status_code == 200, r.text
        assert r.json()["matched_existing_lead"] == 1

        _override([msg])  # exact same message polled a second time
        r = self._poll(client)
        assert r.status_code == 200, r.text
        result = r.json()
        assert result["matched_existing_lead"] == 0
        assert result["leads_created"] == 0
        assert result["errors"] == 0

        insights = client.get(f"/api/v1/leads/{lead['id']}/email-insights", headers=admin_headers).json()
        assert insights["inbound_count"] == 1

    def test_inbound_email_body_is_stored_and_visible_on_the_lead(self, client, admin_headers):
        address = _unique("casey", "meridianhealth.example")
        lead = client.post("/api/v1/leads",
                          json={"company_name": "Meridian Health", "last_name": "Rao",
                                "contact_email": address},
                          headers=admin_headers).json()
        _override([_msg(address, subject="Re: intro", body="Sounds great, let's talk Thursday.")])
        r = self._poll(client)
        assert r.status_code == 200, r.text

        comms = client.get(f"/api/v1/leads/{lead['id']}/communications", headers=admin_headers).json()
        inbound = next(c for c in comms if c["direction"] == "INBOUND")
        assert inbound["body"] == "Sounds great, let's talk Thursday."

    def test_message_with_no_parseable_sender_is_skipped(self, client):
        _override([])  # a From header with no address at all never reaches InboundEmail construction
        r = self._poll(client)
        assert r.status_code == 200, r.text
        assert r.json()["messages_processed"] == 0

    def test_multiple_messages_processed_in_one_poll(self, client, admin_headers):
        _override([
            _msg(_unique("alice"), from_name="Alice A"),
            _msg(_unique("bob"), from_name="Bob B"),
        ])
        r = self._poll(client)
        result = r.json()
        assert result["messages_processed"] == 2
        assert result["leads_created"] == 2
