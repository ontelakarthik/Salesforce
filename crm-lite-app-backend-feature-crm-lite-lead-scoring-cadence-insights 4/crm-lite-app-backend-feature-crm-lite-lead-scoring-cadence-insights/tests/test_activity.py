"""Activity module (§1/§11) — communications, notifications, audit log.
Exercised against the real Postgres container. Audit rows are populated by
the generic create/update/delete hook in repositories/_base.py, not by a
public POST — every mutation these tests perform along the way is itself
what puts rows in audit_log for the audit assertions below.
"""
import uuid

from src.services.auth_service import mint_token_for_profiles


def _bearer(employee_id: str, profile_code: str) -> dict:
    return {"Authorization": f"Bearer {mint_token_for_profiles(employee_id, {profile_code})}"}


def _account_and_agreement(client, admin_headers, ae_headers):
    cust = client.post("/api/v1/accounts", json={"legal_name": "Activity Test Co"},
                      headers=admin_headers).json()["id"]
    agr = client.post("/api/v1/agreements",
                     json={"account_id": cust, "agreement_type": "NDA", "title": "NDA"},
                     headers=ae_headers).json()["id"]
    return cust, agr


class TestCommunications:
    def test_direction_must_be_inbound_or_outbound(self, client, admin_headers, ae_headers):
        cust, _agr = _account_and_agreement(client, admin_headers, ae_headers)
        r = client.post(f"/api/v1/accounts/{cust}/communications",
                        json={"direction": "SIDEWAYS", "channel": "EMAIL",
                             "occurred_at": "2026-02-01T10:00:00Z"},
                        headers=ae_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "INVALID_DIRECTION"

    def test_account_communication_add_and_list(self, client, admin_headers, ae_headers):
        cust, _agr = _account_and_agreement(client, admin_headers, ae_headers)
        r = client.post(f"/api/v1/accounts/{cust}/communications",
                        json={"direction": "OUTBOUND", "channel": "EMAIL", "subject": "Hi",
                             "occurred_at": "2026-02-01T10:00:00Z"},
                        headers=ae_headers)
        assert r.status_code == 201
        r = client.get(f"/api/v1/accounts/{cust}/communications", headers=ae_headers)
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_agreement_communication_add_and_list(self, client, admin_headers, ae_headers):
        _cust, agr = _account_and_agreement(client, admin_headers, ae_headers)
        r = client.post(f"/api/v1/agreements/{agr}/communications",
                        json={"direction": "INBOUND", "channel": "PHONE",
                             "occurred_at": "2026-02-02T10:00:00Z"},
                        headers=ae_headers)
        assert r.status_code == 201
        r = client.get(f"/api/v1/agreements/{agr}/communications", headers=ae_headers)
        assert r.status_code == 200
        assert len(r.json()) == 1


def _lead(client, headers, **overrides):
    payload = {"company_name": "Meridian Health", "contact_email": "test.lead@example.com", "first_name": "Ananya", "last_name": "Rao"} | overrides
    r = client.post("/api/v1/leads", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


class TestLeadCommunications:
    def test_invalid_channel_rejected(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        r = client.post(f"/api/v1/leads/{lead['id']}/communications",
                        json={"direction": "OUTBOUND", "channel": "CARRIER_PIGEON",
                             "occurred_at": "2026-02-01T10:00:00Z"},
                        headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "LEAD_COMMUNICATION_CHANNEL_INVALID"

    def test_invalid_call_outcome_rejected(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        r = client.post(f"/api/v1/leads/{lead['id']}/communications",
                        json={"direction": "OUTBOUND", "channel": "CALL",
                             "occurred_at": "2026-02-01T10:00:00Z", "call_outcome": "GHOSTED"},
                        headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "CALL_OUTCOME_INVALID"

    def test_add_and_list_lead_communication(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        r = client.post(f"/api/v1/leads/{lead['id']}/communications",
                        json={"direction": "OUTBOUND", "channel": "email", "subject": "Intro",
                             "occurred_at": "2026-02-01T10:00:00Z"},
                        headers=admin_headers)
        assert r.status_code == 201, r.text
        assert r.json()["channel"] == "EMAIL"  # normalized uppercase
        assert r.json()["lead_id"] == lead["id"]

        r = client.get(f"/api/v1/leads/{lead['id']}/communications", headers=admin_headers)
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_email_insights_aggregate(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        client.post(f"/api/v1/leads/{lead['id']}/communications",
                   json={"direction": "OUTBOUND", "channel": "EMAIL",
                        "occurred_at": "2026-02-01T10:00:00Z"}, headers=admin_headers)
        client.post(f"/api/v1/leads/{lead['id']}/communications",
                   json={"direction": "INBOUND", "channel": "EMAIL",
                        "occurred_at": "2026-02-02T10:00:00Z"}, headers=admin_headers)
        client.post(f"/api/v1/leads/{lead['id']}/communications",
                   json={"direction": "OUTBOUND", "channel": "CALL",
                        "occurred_at": "2026-02-03T10:00:00Z"}, headers=admin_headers)

        r = client.get(f"/api/v1/leads/{lead['id']}/email-insights", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["total_emails"] == 2
        assert body["inbound_count"] == 1
        assert body["outbound_count"] == 1
        assert body["last_email_at"].startswith("2026-02-02")

    def test_call_insights_aggregate(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        client.post(f"/api/v1/leads/{lead['id']}/communications",
                   json={"direction": "OUTBOUND", "channel": "CALL", "occurred_at": "2026-02-01T10:00:00Z",
                        "call_outcome": "CONNECTED", "call_duration_seconds": 120}, headers=admin_headers)
        client.post(f"/api/v1/leads/{lead['id']}/communications",
                   json={"direction": "OUTBOUND", "channel": "CALL", "occurred_at": "2026-02-02T10:00:00Z",
                        "call_outcome": "NO_ANSWER"}, headers=admin_headers)

        r = client.get(f"/api/v1/leads/{lead['id']}/call-insights", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["total_calls"] == 2
        assert body["connected_count"] == 1
        assert body["connected_rate_percent"] == 50.0
        assert body["avg_duration_seconds"] == 120.0  # only the one call with a duration counts
        assert body["outcome_breakdown"] == {"CONNECTED": 1, "NO_ANSWER": 1}

    def test_sales_cannot_access_unowned_lead_communications(self, client, admin_headers, sales_headers):
        lead = _lead(client, admin_headers)  # owner_employee_id left unset
        r = client.get(f"/api/v1/leads/{lead['id']}/communications", headers=sales_headers)
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "FORBIDDEN"

    def test_call_disposition_is_admin_configurable(self, client, admin_headers):
        """The BRD asks for configurable dispositions — prove a brand-new,
        never-seeded code works end to end via the generic admin lookup
        endpoint, not just the six seeded defaults."""
        code = f"GATEKEEPER_{uuid.uuid4().hex[:6]}".upper()  # lookup codes are always normalized uppercase
        r = client.post("/api/v1/admin/lookups/call_disposition",
                        json={"code": code, "display_name": "Blocked by gatekeeper"},
                        headers=admin_headers)
        assert r.status_code == 201, r.text

        lead = _lead(client, admin_headers)
        r = client.post(f"/api/v1/leads/{lead['id']}/communications",
                        json={"direction": "OUTBOUND", "channel": "CALL",
                             "occurred_at": "2026-02-01T10:00:00Z", "call_outcome": code},
                        headers=admin_headers)
        assert r.status_code == 201, r.text
        assert r.json()["call_outcome"] == code


class TestEmailOpenReplyTracking:
    def test_mark_opened_and_replied_updates_insights(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        comm = client.post(f"/api/v1/leads/{lead['id']}/communications",
                          json={"direction": "OUTBOUND", "channel": "EMAIL",
                               "occurred_at": "2026-02-01T10:00:00Z"}, headers=admin_headers).json()

        r = client.post(f"/api/v1/leads/{lead['id']}/communications/{comm['id']}/opened",
                        json={}, headers=admin_headers)
        assert r.status_code == 200, r.text
        assert r.json()["opened_at"] is not None

        r = client.post(f"/api/v1/leads/{lead['id']}/communications/{comm['id']}/replied",
                        json={}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["replied_at"] is not None

        insights = client.get(f"/api/v1/leads/{lead['id']}/email-insights", headers=admin_headers).json()
        assert insights["opened_count"] == 1
        assert insights["replied_count"] == 1
        assert insights["open_rate_percent"] == 100.0
        assert insights["reply_rate_percent"] == 100.0

    def test_first_open_is_not_overwritten(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        comm = client.post(f"/api/v1/leads/{lead['id']}/communications",
                          json={"direction": "OUTBOUND", "channel": "EMAIL",
                               "occurred_at": "2026-02-01T10:00:00Z"}, headers=admin_headers).json()

        first = client.post(f"/api/v1/leads/{lead['id']}/communications/{comm['id']}/opened",
                           json={"occurred_at": "2026-02-01T11:00:00Z"}, headers=admin_headers).json()
        second = client.post(f"/api/v1/leads/{lead['id']}/communications/{comm['id']}/opened",
                            json={"occurred_at": "2026-02-05T11:00:00Z"}, headers=admin_headers).json()
        assert first["opened_at"] == second["opened_at"]

    def test_cannot_mark_a_call_opened(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        comm = client.post(f"/api/v1/leads/{lead['id']}/communications",
                          json={"direction": "OUTBOUND", "channel": "CALL",
                               "occurred_at": "2026-02-01T10:00:00Z"}, headers=admin_headers).json()

        r = client.post(f"/api/v1/leads/{lead['id']}/communications/{comm['id']}/opened",
                        json={}, headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "NOT_AN_EMAIL"

    def test_email_insights_rates_ignore_inbound(self, client, admin_headers):
        """Open/reply rates are only meaningful against emails we sent —
        an inbound email shouldn't dilute the denominator."""
        lead = _lead(client, admin_headers)
        client.post(f"/api/v1/leads/{lead['id']}/communications",
                   json={"direction": "INBOUND", "channel": "EMAIL",
                        "occurred_at": "2026-02-01T10:00:00Z"}, headers=admin_headers)
        outbound = client.post(f"/api/v1/leads/{lead['id']}/communications",
                              json={"direction": "OUTBOUND", "channel": "EMAIL",
                                   "occurred_at": "2026-02-02T10:00:00Z"}, headers=admin_headers).json()
        client.post(f"/api/v1/leads/{lead['id']}/communications/{outbound['id']}/opened",
                   json={}, headers=admin_headers)

        insights = client.get(f"/api/v1/leads/{lead['id']}/email-insights", headers=admin_headers).json()
        assert insights["total_emails"] == 2
        assert insights["outbound_count"] == 1
        assert insights["opened_count"] == 1
        assert insights["open_rate_percent"] == 100.0  # 1/1 outbound, not 1/2 total


class TestCadenceActivityLogging:
    """Completing a CALL/EMAIL cadence step auto-logs a Communication, tying
    Sales Cadence execution into Email/Call Insights (crm_service.
    complete_cadence_task())."""

    def _enroll(self, client, headers, step_type):
        # create_lead() now auto-enrolls a brand-new lead into whichever
        # CadenceTemplate is currently Active (see crm_service.
        # _auto_enroll_new_lead()) -- a template left Active by an earlier
        # test in this same class would otherwise get this lead auto-
        # enrolled before the explicit .../cadence/enroll call below runs,
        # turning it into a spurious 409 LEAD_ALREADY_IN_ACTIVE_CADENCE.
        for t in client.get("/api/v1/cadence-templates", headers=headers).json():
            if t.get("is_active"):
                client.patch(f"/api/v1/cadence-templates/{t['id']}",
                            json={"is_active": False}, headers=headers)
        lead = client.post("/api/v1/leads",
                          json={"company_name": "Meridian Health", "contact_email": "test.lead@example.com", "last_name": "Rao"},
                          headers=headers).json()
        template = client.post("/api/v1/cadence-templates",
                              json={"name": "Outbound"}, headers=headers).json()
        client.post(f"/api/v1/cadence-templates/{template['id']}/steps",
                   json={"step_order": 1, "step_type": step_type, "subject": "Reach out", "wait_days": 0},
                   headers=headers)
        enrolled = client.post(f"/api/v1/leads/{lead['id']}/cadence/enroll",
                              json={"cadence_template_id": template["id"]}, headers=headers).json()
        return lead, enrolled["tasks"][0]["id"]

    def test_completing_call_step_logs_a_call_activity(self, client, admin_headers):
        lead, task_id = self._enroll(client, admin_headers, "CALL")
        r = client.post(f"/api/v1/cadence-tasks/{task_id}/complete",
                        json={"outcome_status": "DONE"}, headers=admin_headers)
        assert r.status_code == 200

        insights = client.get(f"/api/v1/leads/{lead['id']}/call-insights", headers=admin_headers).json()
        assert insights["total_calls"] == 1

    def test_completing_email_step_logs_an_email_activity(self, client, admin_headers):
        lead, task_id = self._enroll(client, admin_headers, "EMAIL")
        client.post(f"/api/v1/cadence-tasks/{task_id}/complete",
                   json={"outcome_status": "DONE"}, headers=admin_headers)

        insights = client.get(f"/api/v1/leads/{lead['id']}/email-insights", headers=admin_headers).json()
        assert insights["total_emails"] == 1

    def test_skipping_a_step_does_not_log_an_activity(self, client, admin_headers):
        lead, task_id = self._enroll(client, admin_headers, "CALL")
        client.post(f"/api/v1/cadence-tasks/{task_id}/complete",
                   json={"outcome_status": "SKIPPED"}, headers=admin_headers)

        insights = client.get(f"/api/v1/leads/{lead['id']}/call-insights", headers=admin_headers).json()
        assert insights["total_calls"] == 0

    def test_completing_task_step_does_not_log_an_activity(self, client, admin_headers):
        lead, task_id = self._enroll(client, admin_headers, "TASK")
        client.post(f"/api/v1/cadence-tasks/{task_id}/complete",
                   json={"outcome_status": "DONE"}, headers=admin_headers)

        email_insights = client.get(f"/api/v1/leads/{lead['id']}/email-insights", headers=admin_headers).json()
        call_insights = client.get(f"/api/v1/leads/{lead['id']}/call-insights", headers=admin_headers).json()
        assert email_insights["total_emails"] == 0
        assert call_insights["total_calls"] == 0


class TestNotifications:
    def test_list_never_errors_even_when_empty(self, client, admin_headers):
        r = client.get("/api/v1/notifications", headers=admin_headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_acknowledge_missing_notification_404s(self, client, admin_headers):
        r = client.patch(f"/api/v1/notifications/{uuid.uuid4()}/acknowledge", headers=admin_headers)
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "NOTIFICATION_NOT_FOUND"

    def test_list_only_shows_own_targeted_notifications(self, client, admin_headers):
        # Signing an agreement targets a notification at the initiating AE
        # (see contracts_service.sign_agreement) — a second, unrelated AE
        # must not see it in their own /notifications list.
        suffix = uuid.uuid4().hex[:8]
        alice = client.post("/api/v1/admin/employees",
                           json={"email": f"notif.alice.{suffix}@example.com", "full_name": "Notif Alice"},
                           headers=admin_headers).json()["id"]
        bob = client.post("/api/v1/admin/employees",
                         json={"email": f"notif.bob.{suffix}@example.com", "full_name": "Notif Bob"},
                         headers=admin_headers).json()["id"]
        client.put(f"/api/v1/admin/employees/{alice}/profiles", json={"profile_codes": ["ACCOUNT_EXEC"]},
                  headers=admin_headers)
        client.put(f"/api/v1/admin/employees/{bob}/profiles", json={"profile_codes": ["ACCOUNT_EXEC"]},
                  headers=admin_headers)
        alice_headers = _bearer(alice, "ACCOUNT_EXEC")
        bob_headers = _bearer(bob, "ACCOUNT_EXEC")

        _cust, agr = _account_and_agreement(client, admin_headers, alice_headers)
        r = client.post(f"/api/v1/agreements/{agr}/sign", headers=admin_headers)
        assert r.status_code == 200, r.text

        alice_notifs = client.get("/api/v1/notifications", headers=alice_headers).json()
        assert any(n["agreement_id"] == agr and n["notification_type"] == "AGREEMENT_SIGNED"
                  for n in alice_notifs)

        bob_notifs = client.get("/api/v1/notifications", headers=bob_headers).json()
        assert not any(n["agreement_id"] == agr for n in bob_notifs)


class TestAudit:
    def test_sales_has_no_audit_access(self, client, sales_headers):
        r = client.get("/api/v1/audit", headers=sales_headers)
        assert r.status_code == 403

    def test_account_exec_sees_only_rows_they_performed(self, client, admin_headers):
        # Audit's performed_by_employee_id is a hard FK — only a syntactically
        # valid UUID that also matches a real `employee` row gets recorded, so
        # this test provisions two real employees to get a non-trivial scope
        # comparison (see repositories/_base.py's _resolve_employee_uuid).
        suffix = uuid.uuid4().hex[:8]
        alice = client.post("/api/v1/admin/employees",
                           json={"email": f"audit.alice.{suffix}@example.com", "full_name": "Alice"},
                           headers=admin_headers).json()["id"]
        bob = client.post("/api/v1/admin/employees",
                         json={"email": f"audit.bob.{suffix}@example.com", "full_name": "Bob"},
                         headers=admin_headers).json()["id"]
        alice_headers = _bearer(alice, "ACCOUNT_EXEC")
        bob_headers = _bearer(bob, "ACCOUNT_EXEC")

        cust = client.post("/api/v1/accounts", json={"legal_name": "Alice's Account"},
                          headers=alice_headers).json()["id"]
        client.post("/api/v1/accounts", json={"legal_name": "Bob's Account"}, headers=bob_headers)

        r = client.get("/api/v1/audit", headers=alice_headers)
        assert r.status_code == 200
        rows = r.json()
        assert rows, "expected at least Alice's own CREATE row"
        assert all(row["performed_by_employee_id"] == alice for row in rows)
        assert any(row["entity_id"] == cust for row in rows)

    def test_admin_sees_all_and_can_filter_by_entity(self, client, admin_headers, ae_headers):
        cust, _agr = _account_and_agreement(client, admin_headers, ae_headers)
        r = client.get(f"/api/v1/audit?entity_type=account&entity_id={cust}", headers=admin_headers)
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) >= 1
        assert all(row["entity_type"] == "account" and row["entity_id"] == cust for row in rows)
        assert any(row["action"] == "CREATE" for row in rows)
