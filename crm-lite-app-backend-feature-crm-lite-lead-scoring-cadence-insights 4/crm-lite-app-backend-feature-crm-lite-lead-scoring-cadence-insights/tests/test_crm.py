"""CRM module (§1/§6) — accounts, contacts, assignments, opportunities,
opportunity documents. Exercised against the real Postgres container (see
CLAUDE.md: no mock data), same as every other module's tests here.
"""
import pytest


def _create_account(client, headers, **overrides):
    payload = {"legal_name": "Acme Test Co"} | overrides
    r = client.post("/api/v1/accounts", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


class TestAccounts:
    def test_create_account_starts_as_prospect(self, client, admin_headers):
        body = _create_account(client, admin_headers)
        assert body["account_type"] == "PROSPECT"
        assert body["promoted_to_client_at"] is None
        assert body["first_contact_at"] is not None

    def test_creator_becomes_owner_when_none_is_specified(self, client, admin_headers):
        # Real incident: a rep created a lead with no explicit owner, and it
        # came back unowned — immediately outside their own scope the
        # moment they tried to act on it. Accounts follow the same rule.
        import uuid

        from src.services.auth_service import mint_token_for_profiles

        email = f"acctowner.{uuid.uuid4().hex[:8]}@example.com"
        emp = client.post("/api/v1/admin/employees", json={"email": email, "full_name": "Acct Owner"},
                         headers=admin_headers).json()
        rep_headers = {"Authorization": f"Bearer {mint_token_for_profiles(emp['id'], {'SALES'})}"}

        created = _create_account(client, rep_headers)
        assert created["owner_employee_id"] == emp["id"]

        r = client.get(f"/api/v1/accounts/{created['id']}", headers=rep_headers)
        assert r.status_code == 200, "the creator must be able to see their own just-created account"

    def test_get_account_not_found(self, client, admin_headers):
        r = client.get("/api/v1/accounts/ACC-NOPE", headers=admin_headers)
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"

    def test_update_account(self, client, admin_headers):
        cust = _create_account(client, admin_headers)
        r = client.patch(f"/api/v1/accounts/{cust['id']}", json={"industry": "Fintech"},
                         headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["industry"] == "Fintech"

    def test_billing_and_shipping_country_state_are_independent(self, client, admin_headers):
        account = _create_account(
            client, admin_headers,
            billing_country="USA", billing_state_province="California",
            shipping_country="Canada", shipping_state_province="Ontario",
        )
        assert account["billing_country"] == "USA"
        assert account["billing_state_province"] == "California"
        assert account["shipping_country"] == "Canada"
        assert account["shipping_state_province"] == "Ontario"

        # Changing billing must not touch shipping, and vice versa.
        r = client.patch(f"/api/v1/accounts/{account['id']}",
                         json={"billing_country": "Canada", "billing_state_province": "Alberta"},
                         headers=admin_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["billing_country"] == "Canada"
        assert body["billing_state_province"] == "Alberta"
        assert body["shipping_country"] == "Canada"
        assert body["shipping_state_province"] == "Ontario"

    @pytest.mark.parametrize("country,state,expected", [
        ("USA", "California", "West"),
        ("USA", "Texas", "South"),
        ("Canada", "Ontario", "Central Canada"),
        ("Canada", "Quebec", "Central Canada"),
        ("Canada", "Yukon", "North"),
        ("Canada", "Northwest Territories", "North"),
        ("Canada", "Nunavut", "North"),
    ])
    def test_account_region_is_derived_from_billing_country_and_state(
        self, client, admin_headers, country, state, expected,
    ):
        # Region comes from src/utils/geo.py's shared Country -> State ->
        # Region mapping (same one Lead uses) — never copied from
        # billing_state_province itself.
        account = _create_account(
            client, admin_headers, billing_country=country, billing_state_province=state)
        assert account["region"] == expected

    def test_account_region_recalculates_when_billing_country_state_changes(self, client, admin_headers):
        account = _create_account(
            client, admin_headers, billing_country="USA", billing_state_province="California")
        assert account["region"] == "West"

        r = client.patch(f"/api/v1/accounts/{account['id']}",
                         json={"billing_country": "Canada", "billing_state_province": "Nova Scotia"},
                         headers=admin_headers)
        assert r.status_code == 200, r.text
        assert r.json()["region"] == "Atlantic"

    def test_account_region_is_null_without_billing_country_or_state(self, client, admin_headers):
        account = _create_account(client, admin_headers)
        assert account["billing_country"] is None
        assert account["billing_state_province"] is None
        assert account["region"] is None

    def test_shipping_address_defaults_to_billing_when_empty(self, client, admin_headers):
        # Scenario A: Billing has data, Shipping is empty -> Shipping copies
        # Billing (Country + State/Province + Address, not just the text).
        account = _create_account(
            client, admin_headers,
            billing_country="USA", billing_state_province="California",
            address="1600 Amphitheatre Parkway, Mountain View, CA 94043, USA",
        )
        assert account["shipping_country"] == "USA"
        assert account["shipping_state_province"] == "California"
        assert account["shipping_address"] == "1600 Amphitheatre Parkway, Mountain View, CA 94043, USA"
        # Billing itself is untouched by the copy.
        assert account["billing_country"] == "USA"
        assert account["address"] == "1600 Amphitheatre Parkway, Mountain View, CA 94043, USA"

    def test_shipping_address_is_not_overwritten_when_already_set(self, client, admin_headers):
        # Scenario B: Billing has data, Shipping already has data -> keep
        # Shipping as-is.
        account = _create_account(
            client, admin_headers,
            billing_country="USA", billing_state_province="California",
            address="1600 Amphitheatre Parkway, Mountain View, CA 94043, USA",
            shipping_country="USA", shipping_state_province="Texas",
            shipping_address="500 W 2nd St, Austin, TX 78701, USA",
        )
        assert account["shipping_country"] == "USA"
        assert account["shipping_state_province"] == "Texas"
        assert account["shipping_address"] == "500 W 2nd St, Austin, TX 78701, USA"

    def test_shipping_address_stays_empty_when_billing_is_also_empty(self, client, admin_headers):
        # Scenario C: both empty -> Shipping stays empty, never defaults to
        # something else.
        account = _create_account(client, admin_headers)
        assert account["shipping_address"] is None
        assert account["shipping_country"] is None
        assert account["shipping_state_province"] is None

    def test_shipping_address_default_applies_on_update_too(self, client, admin_headers):
        # Billing Address added later, on a patch, while Shipping is still
        # empty -> the default still fires (not just at create time).
        account = _create_account(client, admin_headers)
        assert account["shipping_address"] is None

        r = client.patch(f"/api/v1/accounts/{account['id']}", json={
            "billing_country": "Canada", "billing_state_province": "Ontario",
            "address": "123 King St W, Toronto, ON, Canada",
        }, headers=admin_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["shipping_country"] == "Canada"
        assert body["shipping_state_province"] == "Ontario"
        assert body["shipping_address"] == "123 King St W, Toronto, ON, Canada"

    def test_shipping_address_explicit_value_is_preserved_on_update(self, client, admin_headers):
        # Scenario D: a user-entered Shipping Address is never overwritten by
        # the Billing default, on create or on a later patch.
        account = _create_account(
            client, admin_headers,
            billing_country="USA", billing_state_province="California",
            address="1600 Amphitheatre Parkway, Mountain View, CA 94043, USA",
            shipping_address="PO Box 42, Reno, NV, USA",
        )
        assert account["shipping_address"] == "PO Box 42, Reno, NV, USA"

        r = client.patch(f"/api/v1/accounts/{account['id']}",
                         json={"industry": "Fintech"},
                         headers=admin_headers)
        assert r.status_code == 200, r.text
        assert r.json()["shipping_address"] == "PO Box 42, Reno, NV, USA"

    def test_region_and_shipping_address_persist_after_refresh(self, client, admin_headers):
        # Requirement: values must survive a GET after the write, not just
        # live in the create/update response.
        account = _create_account(
            client, admin_headers,
            billing_country="Canada", billing_state_province="Alberta",
            address="100 Main St, Calgary, AB, Canada",
        )
        r = client.get(f"/api/v1/accounts/{account['id']}", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["region"] == "Prairies"
        assert body["shipping_country"] == "Canada"
        assert body["shipping_state_province"] == "Alberta"
        assert body["shipping_address"] == "100 Main St, Calgary, AB, Canada"

    def test_state_province_without_country_is_rejected(self, client, admin_headers):
        r = client.post("/api/v1/accounts", json={
            "legal_name": "Acme Test Co", "billing_state_province": "California",
        }, headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "STATE_PROVINCE_REQUIRES_COUNTRY"

    def test_state_not_belonging_to_country_is_rejected(self, client, admin_headers):
        r = client.post("/api/v1/accounts", json={
            "legal_name": "Acme Test Co", "billing_country": "USA", "billing_state_province": "Ontario",
        }, headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "INVALID_STATE_PROVINCE"

    def test_list_accounts_returns_page_shape(self, client, admin_headers):
        _create_account(client, admin_headers)
        r = client.get("/api/v1/accounts", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert {"items", "total", "page", "page_size"} <= body.keys()
        assert body["total"] >= 1

    def test_promote_requires_signed_sow(self, client, admin_headers, ae_headers):
        cust = _create_account(client, admin_headers)
        r = client.post(f"/api/v1/accounts/{cust['id']}/promote", headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "PROMOTE_REQUIRES_SIGNED_SOW"

        r = client.post("/api/v1/agreements",
                        json={"account_id": cust["id"], "agreement_type": "SOW", "title": "SOW"},
                        headers=ae_headers)
        assert r.status_code == 201
        sow_id = r.json()["id"]
        r = client.post(f"/api/v1/agreements/{sow_id}/sign", headers=ae_headers)
        assert r.status_code == 200

        r = client.post(f"/api/v1/accounts/{cust['id']}/promote", headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["account_type"] == "CLIENT"

        r = client.post(f"/api/v1/accounts/{cust['id']}/promote", headers=admin_headers)
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "ALREADY_CLIENT"

    def test_delete_blocked_by_active_agreement(self, client, admin_headers, ae_headers):
        cust = _create_account(client, admin_headers)
        client.post("/api/v1/agreements",
                   json={"account_id": cust["id"], "agreement_type": "NDA", "title": "NDA"},
                   headers=ae_headers)
        r = client.delete(f"/api/v1/accounts/{cust['id']}", headers=admin_headers)
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "ACCOUNT_HAS_DEPENDENTS"

    def test_delete_succeeds_with_no_dependents(self, client, admin_headers):
        cust = _create_account(client, admin_headers)
        r = client.delete(f"/api/v1/accounts/{cust['id']}", headers=admin_headers)
        assert r.status_code == 204
        assert client.get(f"/api/v1/accounts/{cust['id']}", headers=admin_headers).status_code == 404


class TestContacts:
    def test_primary_contact_exclusivity(self, client, admin_headers):
        cust = _create_account(client, admin_headers)
        r = client.post(f"/api/v1/accounts/{cust['id']}/contacts",
                        json={"contact_type": "BUSINESS", "full_name": "Alice", "is_primary": True},
                        headers=admin_headers)
        assert r.status_code == 201
        first_id = r.json()["id"]

        r = client.post(f"/api/v1/accounts/{cust['id']}/contacts",
                        json={"contact_type": "LEGAL", "full_name": "Bob", "is_primary": True},
                        headers=admin_headers)
        assert r.status_code == 201

        r = client.get(f"/api/v1/accounts/{cust['id']}/contacts", headers=admin_headers)
        contacts = {c["id"]: c["is_primary"] for c in r.json()}
        assert contacts[first_id] is False  # demoted when Bob became primary

    def test_sales_scope_blocks_contacts_for_unowned_account(self, client, admin_headers, sales_headers):
        cust = _create_account(client, admin_headers)  # owner_employee_id left unset
        r = client.get(f"/api/v1/accounts/{cust['id']}/contacts", headers=sales_headers)
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "FORBIDDEN"

        r = client.post(f"/api/v1/accounts/{cust['id']}/contacts",
                        json={"contact_type": "BUSINESS", "full_name": "Eve"}, headers=sales_headers)
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "FORBIDDEN"

    def test_update_and_delete_contact(self, client, admin_headers):
        cust = _create_account(client, admin_headers)
        r = client.post(f"/api/v1/accounts/{cust['id']}/contacts",
                        json={"contact_type": "BUSINESS", "full_name": "Carol"}, headers=admin_headers)
        assert r.status_code == 201
        contact_id = r.json()["id"]

        r = client.patch(f"/api/v1/contacts/{contact_id}", json={"title": "VP Sales"},
                         headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["title"] == "VP Sales"

        r = client.delete(f"/api/v1/contacts/{contact_id}", headers=admin_headers)
        assert r.status_code == 204
        r = client.get(f"/api/v1/accounts/{cust['id']}/contacts", headers=admin_headers)
        assert contact_id not in {c["id"] for c in r.json()}


class TestAccountAssignments:
    def test_requires_exactly_one_of_employee_or_team(self, client, admin_headers):
        cust = _create_account(client, admin_headers)
        r = client.post(f"/api/v1/accounts/{cust['id']}/assignments",
                        json={"role": "ACCOUNT_EXEC", "assigned_from": "2026-01-01"},
                        headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "ASSIGNMENT_TARGET_INVALID"

        r = client.post(f"/api/v1/accounts/{cust['id']}/assignments", json={
            "employee_id": "00000000-0000-0000-0000-000000000002",
            "team_id": 1, "role": "ACCOUNT_EXEC", "assigned_from": "2026-01-01",
        }, headers=admin_headers)
        assert r.status_code == 422

    def test_create_list_and_update_assignment(self, client, admin_headers):
        cust = _create_account(client, admin_headers)
        emp = client.post("/api/v1/admin/employees",
                         json={"email": f"assignee.{cust['id']}@example.com", "full_name": "Assignee"},
                         headers=admin_headers).json()

        r = client.post(f"/api/v1/accounts/{cust['id']}/assignments", json={
            "employee_id": emp["id"], "role": "ACCOUNT_EXEC", "assigned_from": "2026-01-01",
        }, headers=admin_headers)
        assert r.status_code == 201
        assignment_id = r.json()["id"]

        r = client.get(f"/api/v1/accounts/{cust['id']}/assignments", headers=admin_headers)
        assert r.status_code == 200
        assert any(a["id"] == assignment_id for a in r.json())

        r = client.patch(f"/api/v1/assignments/{assignment_id}",
                         json={"assigned_until": "2026-12-31"}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["assigned_until"] == "2026-12-31"


class TestOpportunities:
    def test_new_opportunity_starts_in_new_stage(self, client, admin_headers, ae_headers):
        cust = _create_account(client, admin_headers)
        r = client.post("/api/v1/opportunities",
                        json={"account_id": cust["id"], "name": "Big Deal"}, headers=ae_headers)
        assert r.status_code == 201
        assert r.json()["stage"] == "NEW"

    def test_creator_becomes_owner_when_none_is_specified(self, client, admin_headers):
        import uuid

        from src.services.auth_service import mint_token_for_profiles

        cust = _create_account(client, admin_headers)
        email = f"opplowner.{uuid.uuid4().hex[:8]}@example.com"
        emp = client.post("/api/v1/admin/employees", json={"email": email, "full_name": "Opp Owner"},
                         headers=admin_headers).json()
        rep_headers = {"Authorization": f"Bearer {mint_token_for_profiles(emp['id'], {'SALES'})}"}

        r = client.post("/api/v1/opportunities",
                        json={"account_id": cust["id"], "name": "My Deal"}, headers=rep_headers)
        assert r.status_code == 201, r.text
        oid = r.json()["id"]
        assert r.json()["owner_employee_id"] == emp["id"]

        r = client.get(f"/api/v1/opportunities/{oid}", headers=rep_headers)
        assert r.status_code == 200, "the creator must be able to see their own just-created opportunity"

    def test_sales_scope_hides_unowned_opportunities(self, client, admin_headers, ae_headers,
                                                     sales_headers):
        cust = _create_account(client, admin_headers)
        r = client.post("/api/v1/opportunities",
                        json={"account_id": cust["id"], "name": "Not Mine"}, headers=ae_headers)
        oid = r.json()["id"]
        r = client.get(f"/api/v1/opportunities/{oid}", headers=sales_headers)
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "FORBIDDEN"
        r = client.get(f"/api/v1/opportunities/{oid}", headers=ae_headers)
        assert r.status_code == 200

    def test_opportunity_document_version_increments(self, client, admin_headers, ae_headers):
        cust = _create_account(client, admin_headers)
        r = client.post("/api/v1/opportunities",
                        json={"account_id": cust["id"], "name": "Deal"}, headers=ae_headers)
        oid = r.json()["id"]

        r = client.post(f"/api/v1/opportunities/{oid}/documents",
                        json={"doc_type": "PROPOSAL", "filename": "v1.pdf"}, headers=ae_headers)
        assert r.status_code == 201
        assert r.json()["version_number"] == 1

        r = client.post(f"/api/v1/opportunities/{oid}/documents",
                        json={"doc_type": "PROPOSAL", "filename": "v2.pdf"}, headers=ae_headers)
        assert r.json()["version_number"] == 2

    def test_update_opportunity_document_status(self, client, admin_headers, ae_headers):
        cust = _create_account(client, admin_headers)
        oid = client.post("/api/v1/opportunities", json={"account_id": cust["id"], "name": "Deal"},
                         headers=ae_headers).json()["id"]
        doc = client.post(f"/api/v1/opportunities/{oid}/documents",
                         json={"doc_type": "PROPOSAL", "filename": "v1.pdf"}, headers=ae_headers).json()

        r = client.patch(f"/api/v1/opportunity-documents/{doc['id']}",
                         json={"status": "APPROVED"}, headers=ae_headers)
        assert r.status_code == 200
        assert r.json()["status"] == "APPROVED"

    def test_delete_opportunity(self, client, admin_headers, ae_headers):
        cust = _create_account(client, admin_headers)
        oid = client.post("/api/v1/opportunities", json={"account_id": cust["id"], "name": "Deal"},
                         headers=ae_headers).json()["id"]
        r = client.delete(f"/api/v1/opportunities/{oid}", headers=ae_headers)
        assert r.status_code == 204
        assert client.get(f"/api/v1/opportunities/{oid}", headers=ae_headers).status_code == 404


class TestCampaigns:
    def test_create_and_list_campaign(self, client, admin_headers):
        r = client.post("/api/v1/campaigns",
                        json={"name": "Healthcare Webinar", "campaign_type": "WEBINAR"},
                        headers=admin_headers)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["is_active"] is True

        r = client.get(f"/api/v1/campaigns/{body['id']}", headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["name"] == "Healthcare Webinar"

        r = client.get("/api/v1/campaigns", headers=admin_headers)
        assert any(c["id"] == body["id"] for c in r.json())

    def test_update_campaign(self, client, admin_headers):
        campaign = client.post("/api/v1/campaigns", json={"name": "Draft Campaign"},
                              headers=admin_headers).json()
        r = client.patch(f"/api/v1/campaigns/{campaign['id']}", json={"is_active": False},
                         headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["is_active"] is False

    def test_leadership_cannot_write_campaigns(self, client, leadership_headers):
        # campaigns.write mirrors accounts.write's role set exactly — SALES
        # can create one (same as SALES creating an Account), LEADERSHIP can't.
        r = client.post("/api/v1/campaigns", json={"name": "Blocked"}, headers=leadership_headers)
        assert r.status_code == 403

    def test_delete_campaign(self, client, admin_headers):
        campaign = client.post("/api/v1/campaigns", json={"name": "Throwaway"},
                              headers=admin_headers).json()
        r = client.delete(f"/api/v1/campaigns/{campaign['id']}", headers=admin_headers)
        assert r.status_code == 204
        assert client.get(f"/api/v1/campaigns/{campaign['id']}", headers=admin_headers).status_code == 404

    def test_delete_campaign_404_when_missing(self, client, admin_headers):
        import uuid

        r = client.delete(f"/api/v1/campaigns/{uuid.uuid4()}", headers=admin_headers)
        assert r.status_code == 404


class TestLeads:
    def _lead(self, client, headers, **overrides):
        payload = {"company_name": "Meridian Health", "contact_email": "test.lead@example.com", "first_name": "Ananya", "last_name": "Rao"} | overrides
        r = client.post("/api/v1/leads", json=payload, headers=headers)
        assert r.status_code == 201, r.text
        return r.json()

    def test_create_lead_starts_new(self, client, admin_headers):
        lead = self._lead(client, admin_headers)
        assert lead["status"] == "NEW"
        assert lead["converted_account_id"] is None

    def test_create_lead_without_email_is_rejected(self, client, admin_headers):
        r = client.post("/api/v1/leads", json={"company_name": "Meridian Health", "last_name": "Rao"},
                        headers=admin_headers)
        assert r.status_code == 422
        assert any(f["loc"][-1] == "contact_email" for f in r.json()["error"]["fields"])

    def test_create_lead_with_blank_email_is_rejected(self, client, admin_headers):
        r = client.post("/api/v1/leads", json={
            "company_name": "Meridian Health", "last_name": "Rao", "contact_email": "   ",
        }, headers=admin_headers)
        assert r.status_code == 422

    def test_create_lead_with_invalid_email_format_is_rejected(self, client, admin_headers):
        r = client.post("/api/v1/leads", json={
            "company_name": "Meridian Health", "last_name": "Rao", "contact_email": "not-an-email",
        }, headers=admin_headers)
        assert r.status_code == 422
        assert any(f["loc"][-1] == "contact_email" for f in r.json()["error"]["fields"])

    def test_create_lead_with_valid_email_succeeds(self, client, admin_headers):
        lead = self._lead(client, admin_headers, contact_email="ananya.rao@example.com")
        assert lead["contact_email"] == "ananya.rao@example.com"

    def test_update_lead_cannot_blank_out_email(self, client, admin_headers):
        lead = self._lead(client, admin_headers)
        r = client.patch(f"/api/v1/leads/{lead['id']}", json={"contact_email": None}, headers=admin_headers)
        assert r.status_code == 422
        r = client.patch(f"/api/v1/leads/{lead['id']}", json={"contact_email": "still-not-an-email"},
                         headers=admin_headers)
        assert r.status_code == 422

    def test_update_lead_can_change_to_another_valid_email(self, client, admin_headers):
        lead = self._lead(client, admin_headers)
        r = client.patch(f"/api/v1/leads/{lead['id']}", json={"contact_email": "new.address@example.com"},
                         headers=admin_headers)
        assert r.status_code == 200, r.text
        assert r.json()["contact_email"] == "new.address@example.com"

    def test_creator_becomes_owner_when_none_is_specified(self, client, admin_headers):
        # Real incident: a SALES rep's own "New lead" submission (no owner
        # field in that form) came back unowned, so their very next click
        # on it ("Start attempting contact") 403'd as outside their own data
        # scope.
        import uuid

        from src.services.auth_service import mint_token_for_profiles

        email = f"leadowner.{uuid.uuid4().hex[:8]}@example.com"
        emp = client.post("/api/v1/admin/employees", json={"email": email, "full_name": "Lead Owner"},
                         headers=admin_headers).json()
        rep_headers = {"Authorization": f"Bearer {mint_token_for_profiles(emp['id'], {'SALES'})}"}

        lead = self._lead(client, rep_headers)
        assert lead["owner_employee_id"] == emp["id"]

        r = client.patch(f"/api/v1/leads/{lead['id']}", json={"status": "ATTEMPTING_CONTACT"}, headers=rep_headers)
        assert r.status_code == 200, "the creator must be able to act on their own just-created lead"

    def test_explicit_owner_is_not_overridden(self, client, admin_headers):
        import uuid

        email = f"explicitowner.{uuid.uuid4().hex[:8]}@example.com"
        emp = client.post("/api/v1/admin/employees", json={"email": email, "full_name": "Explicit Owner"},
                         headers=admin_headers).json()

        lead = self._lead(client, admin_headers, owner_employee_id=emp["id"])
        assert lead["owner_employee_id"] == emp["id"]

    def test_email_intake_leads_stay_unowned_for_triage(self):
        # The one deliberate exception: a lead created by the synthetic
        # email-intake identity (no real, provisioned employee row) must
        # still land unowned for an AE/ADMIN to triage — see
        # crm_service.run_email_intake().
        from src.models import crm_models
        from src.repositories.admin_repository import get_employee_repository
        from src.repositories.crm_repository import get_lead_repository, get_lead_scoring_rule_repository
        from src.services.crm_service import _EMAIL_INTAKE_USER, create_lead

        created = create_lead(
            _EMAIL_INTAKE_USER, get_lead_repository(), get_employee_repository(),
            get_lead_scoring_rule_repository(),
            crm_models.LeadCreate(company_name="example.com", last_name="prospect",
                                  contact_email="cold.prospect@example.com", source="EMAIL"))
        assert created.owner_employee_id is None

    def test_linkedin_url_round_trips_through_create_and_update(self, client, admin_headers):
        lead = self._lead(client, admin_headers, linkedin_url="https://www.linkedin.com/in/ananya-rao")
        assert lead["linkedin_url"] == "https://www.linkedin.com/in/ananya-rao"

        r = client.patch(f"/api/v1/leads/{lead['id']}",
                         json={"linkedin_url": "https://www.linkedin.com/in/ananya-rao-updated"},
                         headers=admin_headers)
        assert r.status_code == 200, r.text
        assert r.json()["linkedin_url"] == "https://www.linkedin.com/in/ananya-rao-updated"

    def test_lead_can_be_linked_to_an_existing_account(self, client, admin_headers):
        account = _create_account(client, admin_headers, billing_country="USA",
                                  billing_state_province="Texas")
        lead = self._lead(client, admin_headers, account_id=account["id"])
        assert lead["account_id"] == account["id"]

        r = client.patch(f"/api/v1/leads/{lead['id']}", json={"account_id": None}, headers=admin_headers)
        assert r.status_code == 200, r.text
        assert r.json()["account_id"] is None

    def test_lead_with_unknown_account_id_is_rejected(self, client, admin_headers):
        r = client.post("/api/v1/leads",
                         json={"company_name": "Meridian Health", "contact_email": "test.lead@example.com", "last_name": "Rao",
                               "account_id": "ACC-NOPE"},
                         headers=admin_headers)
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"

        lead = self._lead(client, admin_headers)
        r = client.patch(f"/api/v1/leads/{lead['id']}", json={"account_id": "ACC-NOPE"}, headers=admin_headers)
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"

    def test_region_is_derived_from_country_and_state(self, client, admin_headers):
        lead = self._lead(client, admin_headers, country="USA", state_province="California")
        assert lead["country"] == "USA"
        assert lead["state_province"] == "California"
        assert lead["region"] == "West"

        r = client.patch(f"/api/v1/leads/{lead['id']}",
                         json={"country": "Canada", "state_province": "Nova Scotia"},
                         headers=admin_headers)
        assert r.status_code == 200, r.text
        assert r.json()["region"] == "Atlantic"

    def test_region_is_null_without_country_or_state(self, client, admin_headers):
        lead = self._lead(client, admin_headers)
        assert lead["country"] is None
        assert lead["state_province"] is None
        assert lead["region"] is None

    def test_region_cannot_be_set_directly(self, client, admin_headers):
        # No `region` input exists on LeadCreate/LeadUpdate — an extra field
        # in the payload is simply ignored by Pydantic, never persisted.
        lead = self._lead(client, admin_headers, country="USA", state_province="Texas", region="Northeast")
        assert lead["region"] == "South"

    def test_invalid_country_state_combination_is_rejected(self, client, admin_headers):
        r = client.post("/api/v1/leads", json={
            "company_name": "Meridian Health", "contact_email": "test.lead@example.com", "last_name": "Rao",
            "country": "USA", "state_province": "Ontario",
        }, headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "INVALID_STATE_PROVINCE"

    def test_lead_not_found(self, client, admin_headers):
        r = client.get("/api/v1/leads/00000000-0000-0000-0000-000000000000", headers=admin_headers)
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "LEAD_NOT_FOUND"

    def test_cannot_skip_straight_to_qualified(self, client, admin_headers):
        lead = self._lead(client, admin_headers)
        r = client.patch(f"/api/v1/leads/{lead['id']}", json={"status": "QUALIFIED"}, headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "LEAD_STATUS_TRANSITION_INVALID"

    def test_convert_requires_qualified(self, client, admin_headers):
        lead = self._lead(client, admin_headers)
        r = client.post(f"/api/v1/leads/{lead['id']}/convert",
                        json={"opportunity_name": "Meridian Deal"}, headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "LEAD_NOT_QUALIFIED"

    def test_convert_creates_account_contact_opportunity(self, client, admin_headers):
        campaign = client.post("/api/v1/campaigns", json={"name": "Healthcare Webinar"},
                              headers=admin_headers).json()
        lead = self._lead(client, admin_headers, campaign_id=campaign["id"],
                          contact_email="ananya@meridianhealth.example", source="Webinar")
        for status in ["ATTEMPTING_CONTACT", "CONTACTED", "QUALIFYING", "QUALIFIED"]:
            r = client.patch(f"/api/v1/leads/{lead['id']}", json={"status": status}, headers=admin_headers)
            assert r.status_code == 200, r.text

        r = client.post(f"/api/v1/leads/{lead['id']}/convert",
                        json={"opportunity_name": "Meridian Health — Data Platform", "estimated_value": 200000},
                        headers=admin_headers)
        assert r.status_code == 200, r.text
        converted = r.json()
        assert converted["status"] == "CONVERTED"
        assert converted["converted_account_id"] is not None
        assert converted["converted_contact_id"] is not None
        assert converted["converted_opportunity_id"] is not None

        cust = client.get(f"/api/v1/accounts/{converted['converted_account_id']}",
                          headers=admin_headers).json()
        assert cust["legal_name"] == "Meridian Health"
        assert cust["account_type"] == "PROSPECT"

        contacts = client.get(f"/api/v1/accounts/{converted['converted_account_id']}/contacts",
                              headers=admin_headers).json()
        assert any(c["id"] == converted["converted_contact_id"] and c["is_primary"] for c in contacts)

        opp = client.get(f"/api/v1/opportunities/{converted['converted_opportunity_id']}",
                         headers=admin_headers).json()
        assert opp["account_id"] == converted["converted_account_id"]
        assert opp["campaign_id"] == campaign["id"]
        assert opp["lead_id"] == lead["id"]

        # A lead can only ever convert once.
        r = client.post(f"/api/v1/leads/{lead['id']}/convert",
                        json={"opportunity_name": "Should not work"}, headers=admin_headers)
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "LEAD_ALREADY_CONVERTED"

    def test_sales_scope_blocks_unowned_lead(self, client, admin_headers, sales_headers):
        lead = self._lead(client, admin_headers)  # owner_employee_id left unset
        r = client.get(f"/api/v1/leads/{lead['id']}", headers=sales_headers)
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "FORBIDDEN"

    def test_delete_lead(self, client, admin_headers):
        lead = self._lead(client, admin_headers)
        r = client.delete(f"/api/v1/leads/{lead['id']}", headers=admin_headers)
        assert r.status_code == 204
        assert client.get(f"/api/v1/leads/{lead['id']}", headers=admin_headers).status_code == 404

    def test_delete_lead_404_when_missing(self, client, admin_headers):
        import uuid

        r = client.delete(f"/api/v1/leads/{uuid.uuid4()}", headers=admin_headers)
        assert r.status_code == 404

    def test_sales_scope_blocks_deleting_unowned_lead(self, client, admin_headers, sales_headers):
        lead = self._lead(client, admin_headers)  # owner_employee_id left unset
        r = client.delete(f"/api/v1/leads/{lead['id']}", headers=sales_headers)
        assert r.status_code == 403

    def test_full_stage_path_is_walkable_one_step_at_a_time(self, client, admin_headers):
        lead = self._lead(client, admin_headers)
        for status in ["ATTEMPTING_CONTACT", "CONTACTED", "QUALIFYING", "QUALIFIED"]:
            r = client.patch(f"/api/v1/leads/{lead['id']}", json={"status": status}, headers=admin_headers)
            assert r.status_code == 200, r.text
            assert r.json()["status"] == status

    def test_cannot_skip_a_stage(self, client, admin_headers):
        lead = self._lead(client, admin_headers)
        client.patch(f"/api/v1/leads/{lead['id']}", json={"status": "ATTEMPTING_CONTACT"}, headers=admin_headers)
        r = client.patch(f"/api/v1/leads/{lead['id']}", json={"status": "QUALIFYING"}, headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "LEAD_STATUS_TRANSITION_INVALID"

    def test_nurturing_can_return_to_an_active_stage(self, client, admin_headers):
        lead = self._lead(client, admin_headers)
        for status in ["ATTEMPTING_CONTACT", "CONTACTED", "NURTURING"]:
            r = client.patch(f"/api/v1/leads/{lead['id']}", json={"status": status}, headers=admin_headers)
            assert r.status_code == 200, r.text
        r = client.patch(f"/api/v1/leads/{lead['id']}", json={"status": "QUALIFYING"}, headers=admin_headers)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "QUALIFYING"

    def test_unqualified_and_disqualified_are_terminal(self, client, admin_headers):
        lead = self._lead(client, admin_headers)
        client.patch(f"/api/v1/leads/{lead['id']}", json={"status": "UNQUALIFIED"}, headers=admin_headers)
        r = client.patch(f"/api/v1/leads/{lead['id']}", json={"status": "ATTEMPTING_CONTACT"}, headers=admin_headers)
        assert r.status_code == 422

    def test_flag_hot_sets_rating(self, client, admin_headers, leadership_headers):
        lead = self._lead(client, admin_headers)
        assert lead["rating"] is None
        r = client.post(f"/api/v1/leads/{lead['id']}/flag-hot", headers=leadership_headers)
        assert r.status_code == 200, r.text
        assert r.json()["rating"] == "HOT"

    def test_flag_hot_forbidden_for_sales(self, client, admin_headers, sales_headers):
        lead = self._lead(client, admin_headers)
        r = client.post(f"/api/v1/leads/{lead['id']}/flag-hot", headers=sales_headers)
        assert r.status_code == 403

    def test_flag_hot_notifies_the_owner(self, client, admin_headers, leadership_headers):
        import uuid
        from src.services.auth_service import mint_token_for_profiles

        owner = client.post("/api/v1/admin/employees",
                            json={"email": f"flaghot.{uuid.uuid4().hex[:8]}@example.com",
                                 "full_name": "Owner Rep"},
                            headers=admin_headers).json()
        lead = self._lead(client, admin_headers, owner_employee_id=owner["id"])
        r = client.post(f"/api/v1/leads/{lead['id']}/flag-hot", headers=leadership_headers)
        assert r.status_code == 200, r.text

        owner_headers = {"Authorization": f"Bearer {mint_token_for_profiles(owner['id'], {'SALES'})}"}
        notifications = client.get("/api/v1/notifications", headers=owner_headers).json()
        matches = [n for n in notifications if n["lead_id"] == lead["id"]]
        assert len(matches) == 1
        assert matches[0]["notification_type"] == "LEAD_FLAGGED_HOT"
        assert matches[0]["recipient_employee_id"] == owner["id"]

    def test_flag_hot_on_unowned_lead_notifies_nobody(self, client, admin_headers, leadership_headers):
        lead = self._lead(client, admin_headers)  # admin_headers has no real linked employee -> unowned
        assert lead["owner_employee_id"] is None
        r = client.post(f"/api/v1/leads/{lead['id']}/flag-hot", headers=leadership_headers)
        assert r.status_code == 200, r.text  # no error just because there's nobody to notify
