"""Project module (§1/§7) — projects CRUD + project-SOW linkage. Exercised
against the real Postgres container.
"""


def _account_and_won_opportunity(client, admin_headers, ae_headers):
    cust = client.post("/api/v1/accounts", json={"legal_name": "Project Test Co"},
                      headers=admin_headers).json()["id"]
    opp = client.post("/api/v1/opportunities", json={"account_id": cust, "name": "Deal"},
                     headers=ae_headers).json()["id"]
    r = client.patch(f"/api/v1/opportunities/{opp}", json={"stage": "WON"}, headers=ae_headers)
    assert r.status_code == 200
    return cust, opp


class TestProjectCreate:
    def test_requires_won_opportunity(self, client, admin_headers, ae_headers):
        cust = client.post("/api/v1/accounts", json={"legal_name": "Project Test Co 2"},
                          headers=admin_headers).json()["id"]
        opp = client.post("/api/v1/opportunities", json={"account_id": cust, "name": "Deal"},
                         headers=ae_headers).json()["id"]  # still NEW
        r = client.post("/api/v1/projects",
                        json={"opportunity_id": opp, "name": "Proj", "start_date": "2026-02-01"},
                        headers=ae_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "OPPORTUNITY_NOT_WON"

    def test_target_end_date_must_not_precede_start_date(self, client, admin_headers, ae_headers):
        _cust, opp = _account_and_won_opportunity(client, admin_headers, ae_headers)
        r = client.post("/api/v1/projects",
                        json={"opportunity_id": opp, "name": "Proj", "start_date": "2026-02-01",
                             "target_end_date": "2026-01-01"},
                        headers=ae_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "INVALID_DATE_RANGE"

    def test_create_inherits_account_and_starts_in_planning(self, client, admin_headers, ae_headers):
        cust, opp = _account_and_won_opportunity(client, admin_headers, ae_headers)
        r = client.post("/api/v1/projects",
                        json={"opportunity_id": opp, "name": "Proj A", "start_date": "2026-02-01"},
                        headers=ae_headers)
        assert r.status_code == 201
        body = r.json()
        assert body["account_id"] == cust
        assert body["status"] == "PLANNING"


class TestProjectCrud:
    def _create_project(self, client, admin_headers, ae_headers):
        _cust, opp = _account_and_won_opportunity(client, admin_headers, ae_headers)
        return client.post("/api/v1/projects",
                          json={"opportunity_id": opp, "name": "Proj", "start_date": "2026-02-01"},
                          headers=ae_headers).json()

    def test_get_and_list(self, client, admin_headers, ae_headers):
        proj = self._create_project(client, admin_headers, ae_headers)
        r = client.get(f"/api/v1/projects/{proj['id']}", headers=ae_headers)
        assert r.status_code == 200
        r = client.get("/api/v1/projects", headers=ae_headers)
        assert r.status_code == 200
        assert any(p["id"] == proj["id"] for p in r.json())

    def test_update_status(self, client, admin_headers, ae_headers):
        proj = self._create_project(client, admin_headers, ae_headers)
        r = client.patch(f"/api/v1/projects/{proj['id']}", json={"status": "ACTIVE"}, headers=ae_headers)
        assert r.status_code == 200
        assert r.json()["status"] == "ACTIVE"

    def test_delete_with_no_sows(self, client, admin_headers, ae_headers):
        proj = self._create_project(client, admin_headers, ae_headers)
        r = client.delete(f"/api/v1/projects/{proj['id']}", headers=admin_headers)
        assert r.status_code == 204

    def test_sales_scope_blocks_project_and_sows_for_unowned_account(
            self, client, admin_headers, ae_headers, sales_headers):
        # _account_and_won_opportunity() creates the account via
        # admin_headers with owner_employee_id left unset, same as
        # test_crm.py::test_sales_scope_blocks_contacts_for_unowned_account.
        proj = self._create_project(client, admin_headers, ae_headers)

        r = client.get(f"/api/v1/projects/{proj['id']}", headers=sales_headers)
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "FORBIDDEN"

        r = client.get("/api/v1/projects", headers=sales_headers)
        assert r.status_code == 200
        assert proj["id"] not in {p["id"] for p in r.json()}

        r = client.get(f"/api/v1/projects/{proj['id']}/sows", headers=sales_headers)
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "FORBIDDEN"

        # AE (sees_all) is unaffected.
        assert client.get(f"/api/v1/projects/{proj['id']}", headers=ae_headers).status_code == 200


class TestProjectSowLinkage:
    def test_create_and_list_project_sow(self, client, admin_headers, ae_headers):
        cust, opp = _account_and_won_opportunity(client, admin_headers, ae_headers)
        proj = client.post("/api/v1/projects",
                          json={"opportunity_id": opp, "name": "Proj", "start_date": "2026-02-01"},
                          headers=ae_headers).json()
        msa = client.post("/api/v1/agreements",
                         json={"account_id": cust, "agreement_type": "MSA", "title": "MSA"},
                         headers=ae_headers).json()["id"]

        r = client.post(f"/api/v1/projects/{proj['id']}/sows",
                        json={"title": "Project SOW", "governing_msa_id": msa, "total_value": 20000},
                        headers=ae_headers)
        assert r.status_code == 201
        body = r.json()
        assert body["agreement"]["agreement_type"] == "SOW"
        assert body["sow_detail"]["project_id"] == proj["id"]

        r = client.get(f"/api/v1/projects/{proj['id']}/sows", headers=ae_headers)
        assert r.status_code == 200
        assert len(r.json()) == 1

    # NOTE: a regression test for create_project_sow's `notes` -> AgreementNote
    # wiring would sit here, but the agreement_note table doesn't exist in
    # this dev DB (the same pre-existing Alembic drift as the documented
    # test_contracts.py::TestNotes baseline failure — see CLAUDE.md). Verified
    # by code review instead; see project_service.create_project_sow.

    def test_delete_blocked_while_sow_active(self, client, admin_headers, ae_headers):
        cust, opp = _account_and_won_opportunity(client, admin_headers, ae_headers)
        proj = client.post("/api/v1/projects",
                          json={"opportunity_id": opp, "name": "Proj", "start_date": "2026-02-01"},
                          headers=ae_headers).json()
        msa = client.post("/api/v1/agreements",
                         json={"account_id": cust, "agreement_type": "MSA", "title": "MSA"},
                         headers=ae_headers).json()["id"]
        client.post(f"/api/v1/projects/{proj['id']}/sows",
                   json={"title": "Project SOW", "governing_msa_id": msa}, headers=ae_headers)

        r = client.delete(f"/api/v1/projects/{proj['id']}", headers=admin_headers)
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "PROJECT_HAS_ACTIVE_SOW"
