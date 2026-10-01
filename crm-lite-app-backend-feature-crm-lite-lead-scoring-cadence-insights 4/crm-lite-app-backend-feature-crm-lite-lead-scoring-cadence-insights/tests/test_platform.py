"""Platform module (§1/§12) — dashboard, search, lookup reads, document
upload URLs. Exercised against the real Postgres container.
"""
import uuid


def _employee(client, admin_headers, **overrides):
    payload = {"email": f"mgr-dash.{uuid.uuid4().hex[:8]}@example.com", "full_name": "Dashboard Rep"} | overrides
    return client.post("/api/v1/admin/employees", json=payload, headers=admin_headers).json()["id"]


class TestManagerDashboard:
    """This is a persistent, shared Postgres DB with no per-test rollback —
    every assertion below scopes to a freshly-created employee_id so counts
    are exact regardless of leftover leads from other tests/runs."""

    def test_sales_forbidden(self, client, sales_headers):
        r = client.get("/api/v1/manager-dashboard", headers=sales_headers)
        assert r.status_code == 403

    def test_account_exec_forbidden(self, client, ae_headers):
        """Part of the dashboard split: ACCOUNT_EXEC now sees the personal
        rep dashboard, not the manager one — only LEADERSHIP/ADMIN do."""
        r = client.get("/api/v1/manager-dashboard", headers=ae_headers)
        assert r.status_code == 403

    def test_counts_and_pipeline_for_one_rep(self, client, admin_headers):
        rep = _employee(client, admin_headers)
        unique_industry = f"industry-{uuid.uuid4()}"
        lead1 = client.post("/api/v1/leads",
                           json={"company_name": "A", "contact_email": "test.lead@example.com", "last_name": "One", "owner_employee_id": rep,
                                "industry": unique_industry},
                           headers=admin_headers).json()
        lead2 = client.post("/api/v1/leads",
                           json={"company_name": "B", "contact_email": "test.lead@example.com", "last_name": "Two", "owner_employee_id": rep,
                                "industry": unique_industry},
                           headers=admin_headers).json()
        for status in ["ATTEMPTING_CONTACT", "CONTACTED", "QUALIFYING", "QUALIFIED"]:
            r = client.patch(f"/api/v1/leads/{lead2['id']}", json={"status": status}, headers=admin_headers)
            assert r.status_code == 200, r.text

        client.post(f"/api/v1/leads/{lead1['id']}/communications",
                   json={"direction": "OUTBOUND", "channel": "EMAIL", "occurred_at": "2026-02-01T10:00:00Z"},
                   headers=admin_headers)
        client.post(f"/api/v1/leads/{lead1['id']}/communications",
                   json={"direction": "OUTBOUND", "channel": "CALL", "occurred_at": "2026-02-01T10:05:00Z"},
                   headers=admin_headers)

        r = client.get(f"/api/v1/manager-dashboard?owner_employee_id={rep}", headers=admin_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total_leads"] == 2
        assert body["leads_by_status"] == {"NEW": 1, "QUALIFIED": 1}
        assert body["conversion_rate_percent"] == 0.0  # none CONVERTED yet
        assert len(body["per_rep"]) == 1
        rep_row = body["per_rep"][0]
        assert rep_row["owner_employee_id"] == rep
        assert rep_row["leads_created"] == 2
        assert rep_row["leads_qualified"] == 1
        assert rep_row["emails_sent"] == 1
        assert rep_row["calls_made"] == 1
        assert body["team_totals"]["leads_created"] == 2

    def test_contacted_and_responded_lead_counts(self, client, admin_headers):
        """BRD Phase 3 #10/#11 — Contacted (>=1 EMAIL/CALL communication,
        counted once per lead even with multiple activities) and Responded
        (>=1 INBOUND communication) computed from real Communication rows,
        not hardcoded."""
        rep = _employee(client, admin_headers)
        lead_a = client.post("/api/v1/leads", json={
            "company_name": "A", "contact_email": "a@example.com", "last_name": "One", "owner_employee_id": rep,
        }, headers=admin_headers).json()
        lead_b = client.post("/api/v1/leads", json={
            "company_name": "B", "contact_email": "b@example.com", "last_name": "Two", "owner_employee_id": rep,
        }, headers=admin_headers).json()
        lead_c = client.post("/api/v1/leads", json={
            "company_name": "C", "contact_email": "c@example.com", "last_name": "Three", "owner_employee_id": rep,
        }, headers=admin_headers).json()
        client.post("/api/v1/leads", json={
            "company_name": "D", "contact_email": "d@example.com", "last_name": "Four", "owner_employee_id": rep,
        }, headers=admin_headers)  # lead D: no communication at all

        # Lead A: two outbound emails — still one "contacted" lead.
        for _ in range(2):
            client.post(f"/api/v1/leads/{lead_a['id']}/communications",
                       json={"direction": "OUTBOUND", "channel": "EMAIL", "occurred_at": "2026-02-01T10:00:00Z"},
                       headers=admin_headers)
        # Lead B: a logged call — contacted via a different channel.
        client.post(f"/api/v1/leads/{lead_b['id']}/communications",
                   json={"direction": "OUTBOUND", "channel": "CALL", "occurred_at": "2026-02-01T10:00:00Z"},
                   headers=admin_headers)
        # Lead C: sent email + an inbound reply — contacted AND responded.
        client.post(f"/api/v1/leads/{lead_c['id']}/communications",
                   json={"direction": "OUTBOUND", "channel": "EMAIL", "occurred_at": "2026-02-01T10:00:00Z"},
                   headers=admin_headers)
        client.post(f"/api/v1/leads/{lead_c['id']}/communications",
                   json={"direction": "INBOUND", "channel": "EMAIL", "occurred_at": "2026-02-01T11:00:00Z"},
                   headers=admin_headers)

        r = client.get(f"/api/v1/manager-dashboard?owner_employee_id={rep}", headers=admin_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["team_totals"]["leads_contacted"] == 3  # A, B, C — not D
        assert body["team_totals"]["leads_responded"] == 1  # only C
        assert len(body["per_rep"]) == 1
        assert body["per_rep"][0]["leads_contacted"] == 3
        assert body["per_rep"][0]["leads_responded"] == 1

    def test_industry_filter_excludes_other_industries(self, client, admin_headers):
        rep = _employee(client, admin_headers)
        target_industry = f"target-{uuid.uuid4()}"
        other_industry = f"other-{uuid.uuid4()}"
        client.post("/api/v1/leads", json={"company_name": "A", "contact_email": "test.lead@example.com", "last_name": "One",
                                          "owner_employee_id": rep, "industry": target_industry},
                   headers=admin_headers)
        client.post("/api/v1/leads", json={"company_name": "B", "contact_email": "test.lead@example.com", "last_name": "Two",
                                          "owner_employee_id": rep, "industry": other_industry},
                   headers=admin_headers)

        r = client.get(f"/api/v1/manager-dashboard?owner_employee_id={rep}&industry={target_industry}",
                       headers=admin_headers)
        assert r.json()["total_leads"] == 1

    def test_hot_lead_count_uses_threshold(self, client, admin_headers):
        rep = _employee(client, admin_headers)
        unique_industry = f"industry-{uuid.uuid4()}"
        client.post("/api/v1/lead-scoring-rules",
                   json={"name": "hot", "field_name": "industry", "operator": "EQUALS",
                        "comparison_value": unique_industry, "points": 80},
                   headers=admin_headers)
        client.post("/api/v1/leads", json={"company_name": "A", "contact_email": "test.lead@example.com", "last_name": "One",
                                          "owner_employee_id": rep, "industry": unique_industry},
                   headers=admin_headers)

        r = client.get(f"/api/v1/manager-dashboard?owner_employee_id={rep}&hot_lead_score_threshold=50",
                       headers=admin_headers)
        assert r.json()["hot_lead_count"] == 1

        r = client.get(f"/api/v1/manager-dashboard?owner_employee_id={rep}&hot_lead_score_threshold=90",
                       headers=admin_headers)
        assert r.json()["hot_lead_count"] == 0

    def test_leaderboard_sorted_by_activity_descending(self, client, admin_headers):
        busy_rep = _employee(client, admin_headers)
        quiet_rep = _employee(client, admin_headers)
        unique_industry = f"industry-{uuid.uuid4()}"
        for _ in range(3):
            client.post("/api/v1/leads", json={"company_name": "A", "contact_email": "test.lead@example.com", "last_name": "One",
                                              "owner_employee_id": busy_rep, "industry": unique_industry},
                       headers=admin_headers)
        client.post("/api/v1/leads", json={"company_name": "B", "contact_email": "test.lead@example.com", "last_name": "Two",
                                          "owner_employee_id": quiet_rep, "industry": unique_industry},
                   headers=admin_headers)

        r = client.get(f"/api/v1/manager-dashboard?industry={unique_industry}", headers=admin_headers)
        leaderboard = r.json()["leaderboard"]
        ranked_owners = [row["owner_employee_id"] for row in leaderboard]
        assert ranked_owners.index(busy_rep) < ranked_owners.index(quiet_rep)


class TestLeadDrillDownFilters:
    def test_filter_leads_by_owner_and_status(self, client, admin_headers):
        rep = _employee(client, admin_headers)
        lead = client.post("/api/v1/leads", json={"company_name": "A", "contact_email": "test.lead@example.com", "last_name": "One",
                                                  "owner_employee_id": rep},
                          headers=admin_headers).json()
        other = client.post("/api/v1/leads", json={"company_name": "B", "contact_email": "test.lead@example.com", "last_name": "Two"},
                           headers=admin_headers).json()

        r = client.get(f"/api/v1/leads?owner_employee_id={rep}", headers=admin_headers)
        ids = {lead_row["id"] for lead_row in r.json()}
        assert lead["id"] in ids
        assert other["id"] not in ids

        r = client.get(f"/api/v1/leads?owner_employee_id={rep}&status=DISQUALIFIED", headers=admin_headers)
        assert r.json() == []


class TestDashboard:
    def test_shape_and_admin_sees_global_counts(self, client, admin_headers):
        client.post("/api/v1/accounts", json={"legal_name": "Dashboard Test Co"}, headers=admin_headers)
        r = client.get("/api/v1/dashboard", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert {"total_accounts", "total_agreements", "agreements_by_status", "overdue_agreements",
                "total_projects", "projects_by_status", "pending_timesheets",
                "unacknowledged_notifications"} <= body.keys()
        assert body["total_accounts"] >= 1

    def test_sales_without_owned_accounts_sees_zero(self, client, sales_headers):
        r = client.get("/api/v1/dashboard", headers=sales_headers)
        assert r.status_code == 200
        assert r.json()["total_accounts"] == 0


class TestSearch:
    def test_finds_account_by_name_fragment(self, client, admin_headers):
        r = client.post("/api/v1/accounts", json={"legal_name": "Zebra Search Target Inc"},
                       headers=admin_headers)
        cust_id = r.json()["id"]
        r = client.get("/api/v1/search?q=Zebra Search", headers=admin_headers)
        assert r.status_code == 200
        results = r.json()["results"]
        assert any(item["entity_type"] == "account" and item["id"] == cust_id for item in results)

    def test_empty_query_returns_no_results(self, client, admin_headers):
        r = client.get("/api/v1/search?q=", headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["results"] == []


class TestLookups:
    def test_read_known_table(self, client, admin_headers):
        r = client.get("/api/v1/lookups/account_type", headers=admin_headers)
        assert r.status_code == 200
        codes = {row["code"] for row in r.json()}
        assert "PROSPECT" in codes and "CLIENT" in codes

    def test_unknown_table_404s(self, client, admin_headers):
        r = client.get("/api/v1/lookups/not_a_real_table", headers=admin_headers)
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "LOOKUP_TABLE_NOT_FOUND"


class TestUploadUrl:
    def test_returns_placeholder_upload_contract(self, client, admin_headers):
        r = client.post("/api/v1/documents/upload-url",
                        json={"filename": "contract.pdf", "content_type": "application/pdf"},
                        headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["sharepoint_item_id"]
        assert body["upload_url"].endswith("contract.pdf")
        assert body["expires_at"]
