"""Campaign email sending (POST /campaigns/{id}/send) — blasts a subject/body
to every lead in the campaign the caller can see, logging one Communication
per successful send. Same fake-provider-via-dependency-override pattern as
test_email_sending.py; every test here overrides get_email_sender explicitly
so a run never attempts a real send through whatever SMTP_HOST happens to be
configured in the ambient environment.
"""
import uuid

from src.server import app
from src.services.auth_service import mint_token_for_profiles
from src.services.email_client import get_email_sender
from src.utils.exceptions import DomainError


class _FakeEmailSender:
    def __init__(self, fail_for: set[str] | None = None):
        self.fail_for = fail_for or set()
        self.sent: list[tuple[str, str, str]] = []

    def send(self, to_address: str, subject: str, body: str) -> None:
        if to_address in self.fail_for:
            raise DomainError("EMAIL_SEND_FAILED", "simulated failure", 502)
        self.sent.append((to_address, subject, body))


def _override(fake):
    app.dependency_overrides[get_email_sender] = lambda: fake


def _clear_override():
    app.dependency_overrides.pop(get_email_sender, None)


def _campaign(client, headers, **overrides):
    payload = {"name": "Healthcare Webinar"} | overrides
    r = client.post("/api/v1/campaigns", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _lead(client, headers, **overrides):
    payload = {"company_name": "Meridian Health", "contact_email": "test.lead@example.com", "first_name": "Ananya", "last_name": "Rao"} | overrides
    r = client.post("/api/v1/leads", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


class TestCampaignSend:
    def teardown_method(self):
        _clear_override()

    def test_sends_to_every_targeted_lead_and_logs_communications(self, client, admin_headers):
        campaign = _campaign(client, admin_headers)
        lead_a = _lead(client, admin_headers, campaign_id=campaign["id"], contact_email="a@example.com")
        lead_b = _lead(client, admin_headers, campaign_id=campaign["id"], contact_email="b@example.com",
                       last_name="Iyer")
        fake = _FakeEmailSender()
        _override(fake)

        r = client.post(f"/api/v1/campaigns/{campaign['id']}/send",
                        json={"subject": "Join our webinar", "body": "You're invited."}, headers=admin_headers)
        assert r.status_code == 200, r.text
        result = r.json()
        assert result["total_targeted"] == 2
        assert result["sent"] == 2
        assert result["skipped_no_email"] == 0
        assert result["skipped_opted_out"] == 0
        assert result["failed"] == 0
        assert {s[0] for s in fake.sent} == {"a@example.com", "b@example.com"}

        insights_a = client.get(f"/api/v1/leads/{lead_a['id']}/email-insights", headers=admin_headers).json()
        assert insights_a["outbound_count"] == 1
        insights_b = client.get(f"/api/v1/leads/{lead_b['id']}/email-insights", headers=admin_headers).json()
        assert insights_b["outbound_count"] == 1

    def test_skips_opted_out_leads(self, client, admin_headers):
        campaign = _campaign(client, admin_headers)
        _lead(client, admin_headers, campaign_id=campaign["id"],
             contact_email="opted-out@example.com", email_opt_out=True)
        _override(_FakeEmailSender())

        r = client.post(f"/api/v1/campaigns/{campaign['id']}/send",
                        json={"subject": "Hi", "body": "B"}, headers=admin_headers)
        assert r.status_code == 200, r.text
        result = r.json()
        assert result["sent"] == 0
        assert result["skipped_opted_out"] == 1

    def test_one_recipient_failure_does_not_abort_the_rest(self, client, admin_headers):
        campaign = _campaign(client, admin_headers)
        _lead(client, admin_headers, campaign_id=campaign["id"], contact_email="good@example.com")
        _lead(client, admin_headers, campaign_id=campaign["id"], contact_email="bad@example.com",
             last_name="Iyer")
        _override(_FakeEmailSender(fail_for={"bad@example.com"}))

        r = client.post(f"/api/v1/campaigns/{campaign['id']}/send",
                        json={"subject": "Hi", "body": "B"}, headers=admin_headers)
        assert r.status_code == 200, r.text
        result = r.json()
        assert result["sent"] == 1
        assert result["failed"] == 1

    def test_num_sent_accumulates_on_the_campaign(self, client, admin_headers):
        campaign = _campaign(client, admin_headers)
        _lead(client, admin_headers, campaign_id=campaign["id"], contact_email="a@example.com")
        _override(_FakeEmailSender())

        client.post(f"/api/v1/campaigns/{campaign['id']}/send",
                   json={"subject": "Hi", "body": "B"}, headers=admin_headers)
        updated = client.get(f"/api/v1/campaigns/{campaign['id']}", headers=admin_headers).json()
        assert updated["num_sent"] == 1

    def test_campaign_not_found(self, client, admin_headers):
        _override(_FakeEmailSender())
        r = client.post("/api/v1/campaigns/00000000-0000-0000-0000-000000000000/send",
                        json={"subject": "Hi", "body": "B"}, headers=admin_headers)
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "CAMPAIGN_NOT_FOUND"

    def test_sales_only_reaches_leads_they_own(self, client, admin_headers):
        # owner_employee_id must resolve to a real Employee row (see
        # crm_service._validate_owner) — mint a token for that same real id
        # rather than the synthetic sales_headers fixture's placeholder UUID.
        emp = client.post("/api/v1/admin/employees",
                          json={"email": f"rep.{uuid.uuid4().hex[:8]}@example.com", "full_name": "Rep One"},
                          headers=admin_headers).json()
        rep_headers = {"Authorization": f"Bearer {mint_token_for_profiles(emp['id'], {'SALES'})}"}

        campaign = _campaign(client, admin_headers)
        _lead(client, admin_headers, campaign_id=campaign["id"], contact_email="unowned@example.com")
        _lead(client, admin_headers, campaign_id=campaign["id"], contact_email="owned@example.com",
             last_name="Iyer", owner_employee_id=emp["id"])
        fake = _FakeEmailSender()
        _override(fake)

        r = client.post(f"/api/v1/campaigns/{campaign['id']}/send",
                        json={"subject": "Hi", "body": "B"}, headers=rep_headers)
        assert r.status_code == 200, r.text
        result = r.json()
        assert result["total_targeted"] == 1
        assert result["sent"] == 1
        assert fake.sent[0][0] == "owned@example.com"

    def test_leadership_cannot_send_campaign_email(self, client, admin_headers, leadership_headers):
        campaign = _campaign(client, admin_headers)
        _override(_FakeEmailSender())
        r = client.post(f"/api/v1/campaigns/{campaign['id']}/send",
                        json={"subject": "Hi", "body": "B"}, headers=leadership_headers)
        assert r.status_code == 403
