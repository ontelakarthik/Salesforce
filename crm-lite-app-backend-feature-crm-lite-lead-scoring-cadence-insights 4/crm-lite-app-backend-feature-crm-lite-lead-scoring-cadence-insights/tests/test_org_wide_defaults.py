"""Organization-Wide Defaults — admin-configurable per-object (LEAD/ACCOUNT/
CONTACT/OPPORTUNITY/CAMPAIGN) baseline row-visibility. See
services/record_access_service.py (the centralized decision point these
enforcement tests exercise) and crm_models.OrgWideDefault.

Role Hierarchy is included for these 5 objects as an additional access path
alongside OWD/sharing, never a replacement for it — see
TestRecordAccessIncludesRoleHierarchy below, and
services/record_access_service.py's module docstring. (Agreement/Project/
SOW/Communications separately consult Role Hierarchy via src/utils/scope.py,
untouched by anything in this file.)

This is a persistent, shared Postgres DB with no per-test rollback, and
unlike FieldPermission (many independent (role, object, field) rows) there
are only ever exactly 5 OrgWideDefault rows shared by the ENTIRE test suite
— every other test module's scoping assertions (test_crm.py, test_profiles.py,
test_field_permissions.py, ...) implicitly assumes PRIVATE. The autouse
fixture below resets all five back to PRIVATE both before and after every
test in this module so no other test file can observe a non-default setting.
"""
import uuid

import pytest

from src.services.auth_service import mint_token_for_profiles

OWD_OBJECTS = ("LEAD", "ACCOUNT", "CONTACT", "OPPORTUNITY", "CAMPAIGN")

_ALL_PRIVATE = {"entries": [{"object_name": name, "access_level": "PRIVATE"} for name in OWD_OBJECTS]}


@pytest.fixture(autouse=True)
def _reset_owd(client, admin_headers):
    def _set_all_private():
        r = client.put("/api/v1/org-wide-defaults", json=_ALL_PRIVATE, headers=admin_headers)
        assert r.status_code == 200, r.text

    _set_all_private()
    yield
    _set_all_private()


def _unique_code() -> str:
    return f"TESTOWD{uuid.uuid4().hex[:8].upper()}"


def _create_profile(client, admin_headers, display_name="OWD Test Profile") -> dict:
    r = client.post("/api/v1/admin/profiles", json={"code": _unique_code(), "display_name": display_name},
                    headers=admin_headers)
    assert r.status_code == 201, r.text
    return r.json()


def _employee_with_capabilities(client, admin_headers, capability_keys, full_name) -> tuple[str, dict]:
    """A fresh profile granted exactly `capability_keys` (no records.see_all,
    no role-hierarchy relationship to anyone) — isolates the OWD row-scope
    gate from both the capability gate and any hierarchy-widening path."""
    profile = _create_profile(client, admin_headers, display_name=full_name)
    r = client.put(f"/api/v1/admin/profiles/{profile['id']}/capabilities",
                  json={"capability_keys": capability_keys}, headers=admin_headers)
    assert r.status_code == 200, r.text
    emp = client.post("/api/v1/admin/employees",
                      json={"email": f"owdtest.{uuid.uuid4().hex[:8]}@example.com", "full_name": full_name},
                      headers=admin_headers).json()
    r = client.put(f"/api/v1/admin/employees/{emp['id']}/profiles",
                  json={"profile_codes": [profile["code"]]}, headers=admin_headers)
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {mint_token_for_profiles(emp['id'], {profile['code']})}"}
    return emp["id"], headers


def _real_employee(client, admin_headers, full_name) -> str:
    emp = client.post("/api/v1/admin/employees",
                      json={"email": f"owdowner.{uuid.uuid4().hex[:8]}@example.com", "full_name": full_name},
                      headers=admin_headers).json()
    return emp["id"]


def _set_owd(client, admin_headers, object_name: str, access_level: str) -> None:
    entries = [
        {"object_name": name, "access_level": access_level if name == object_name else "PRIVATE"}
        for name in OWD_OBJECTS
    ]
    r = client.put("/api/v1/org-wide-defaults", json={"entries": entries}, headers=admin_headers)
    assert r.status_code == 200, r.text


class TestOrgWideDefaultAdminCrud:
    def test_non_admin_cannot_read_or_write(self, client, sales_headers, leadership_headers):
        r = client.get("/api/v1/org-wide-defaults", headers=sales_headers)
        assert r.status_code == 403
        r = client.put("/api/v1/org-wide-defaults", json=_ALL_PRIVATE, headers=leadership_headers)
        assert r.status_code == 403

    def test_get_returns_all_five_private_by_default(self, client, admin_headers):
        r = client.get("/api/v1/org-wide-defaults", headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["defaults"] == {name: "PRIVATE" for name in OWD_OBJECTS}

    def test_save_round_trips(self, client, admin_headers):
        payload = {"entries": [
            {"object_name": "LEAD", "access_level": "PUBLIC_READ_ONLY"},
            {"object_name": "ACCOUNT", "access_level": "PRIVATE"},
            {"object_name": "CONTACT", "access_level": "PRIVATE"},
            {"object_name": "OPPORTUNITY", "access_level": "PUBLIC_READ_WRITE"},
            {"object_name": "CAMPAIGN", "access_level": "PUBLIC_READ_ONLY"},
        ]}
        expected = {
            "LEAD": "PUBLIC_READ_ONLY", "ACCOUNT": "PRIVATE", "CONTACT": "PRIVATE",
            "OPPORTUNITY": "PUBLIC_READ_WRITE", "CAMPAIGN": "PUBLIC_READ_ONLY",
        }
        r = client.put("/api/v1/org-wide-defaults", json=payload, headers=admin_headers)
        assert r.status_code == 200, r.text
        assert r.json()["defaults"] == expected

        r = client.get("/api/v1/org-wide-defaults", headers=admin_headers)
        assert r.json()["defaults"] == expected

    def test_save_requires_all_objects(self, client, admin_headers):
        payload = {"entries": [{"object_name": "LEAD", "access_level": "PUBLIC_READ_ONLY"}]}
        r = client.put("/api/v1/org-wide-defaults", json=payload, headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "OWD_INCOMPLETE_SUBMISSION"

    def test_save_rejects_unknown_object(self, client, admin_headers):
        payload = {"entries": [{"object_name": name, "access_level": "PRIVATE"} for name in OWD_OBJECTS]
                   + [{"object_name": "WIDGET", "access_level": "PRIVATE"}]}
        r = client.put("/api/v1/org-wide-defaults", json=payload, headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "OWD_OBJECT_UNKNOWN"

    def test_save_rejects_invalid_access_level(self, client, admin_headers):
        payload = {"entries": [
            {"object_name": "LEAD", "access_level": "EVERYONE"},
            {"object_name": "ACCOUNT", "access_level": "PRIVATE"},
            {"object_name": "CONTACT", "access_level": "PRIVATE"},
            {"object_name": "OPPORTUNITY", "access_level": "PRIVATE"},
            {"object_name": "CAMPAIGN", "access_level": "PRIVATE"},
        ]}
        r = client.put("/api/v1/org-wide-defaults", json=payload, headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "OWD_ACCESS_LEVEL_INVALID"


class TestOrgWideDefaultEnforcementLead:
    """A profile holding leads.read + leads.edit, but neither records.see_all
    nor any role-hierarchy relationship to the lead's owner — isolates the
    LEAD OWD gate from every other layer."""

    def test_private_reproduces_todays_behavior(self, client, admin_headers):
        owner_id = _real_employee(client, admin_headers, "Lead Owner Private")
        _, tester_headers = _employee_with_capabilities(
            client, admin_headers, ["leads.read", "leads.edit"], "Lead Tester Private")
        lead = client.post("/api/v1/leads", json={
            "company_name": "OWD Private Co", "contact_email": "test.lead@example.com", "last_name": "Doe", "owner_employee_id": owner_id,
        }, headers=admin_headers)
        assert lead.status_code == 201, lead.text
        lid = lead.json()["id"]

        r = client.get(f"/api/v1/leads/{lid}", headers=tester_headers)
        assert r.status_code == 403

    def test_public_read_only_allows_read_but_blocks_write(self, client, admin_headers):
        owner_id = _real_employee(client, admin_headers, "Lead Owner RO")
        _, tester_headers = _employee_with_capabilities(
            client, admin_headers, ["leads.read", "leads.edit"], "Lead Tester RO")
        lead = client.post("/api/v1/leads", json={
            "company_name": "OWD RO Co", "contact_email": "test.lead@example.com", "last_name": "Doe", "owner_employee_id": owner_id,
        }, headers=admin_headers)
        lid = lead.json()["id"]
        _set_owd(client, admin_headers, "LEAD", "PUBLIC_READ_ONLY")

        r = client.get(f"/api/v1/leads/{lid}", headers=tester_headers)
        assert r.status_code == 200, r.text

        r = client.patch(f"/api/v1/leads/{lid}", json={"title": "Changed"}, headers=tester_headers)
        assert r.status_code == 403

    def test_public_read_write_allows_read_and_write(self, client, admin_headers):
        owner_id = _real_employee(client, admin_headers, "Lead Owner RW")
        _, tester_headers = _employee_with_capabilities(
            client, admin_headers, ["leads.read", "leads.edit"], "Lead Tester RW")
        lead = client.post("/api/v1/leads", json={
            "company_name": "OWD RW Co", "contact_email": "test.lead@example.com", "last_name": "Doe", "owner_employee_id": owner_id,
        }, headers=admin_headers)
        lid = lead.json()["id"]
        _set_owd(client, admin_headers, "LEAD", "PUBLIC_READ_WRITE")

        r = client.get(f"/api/v1/leads/{lid}", headers=tester_headers)
        assert r.status_code == 200

        r = client.patch(f"/api/v1/leads/{lid}", json={"title": "Changed"}, headers=tester_headers)
        assert r.status_code == 200, r.text
        assert r.json()["title"] == "Changed"

    def test_records_see_all_still_sees_everything_regardless_of_owd(self, client, admin_headers,
                                                                       leadership_headers):
        owner_id = _real_employee(client, admin_headers, "Lead Owner SeeAll")
        lead = client.post("/api/v1/leads", json={
            "company_name": "OWD SeeAll Co", "contact_email": "test.lead@example.com", "last_name": "Doe", "owner_employee_id": owner_id,
        }, headers=admin_headers)
        lid = lead.json()["id"]
        # LEAD stays PRIVATE (the fixture default) — LEADERSHIP holds
        # records.see_all and must see it anyway.
        r = client.get(f"/api/v1/leads/{lid}", headers=leadership_headers)
        assert r.status_code == 200


class TestOrgWideDefaultEnforcementAccount:
    def test_private_reproduces_todays_behavior(self, client, admin_headers):
        owner_id = _real_employee(client, admin_headers, "Account Owner Private")
        _, tester_headers = _employee_with_capabilities(
            client, admin_headers, ["accounts.read", "accounts.edit"], "Account Tester Private")
        account = client.post("/api/v1/accounts", json={
            "legal_name": "OWD Private Account", "owner_employee_id": owner_id,
        }, headers=admin_headers)
        assert account.status_code == 201, account.text
        aid = account.json()["id"]

        r = client.get(f"/api/v1/accounts/{aid}", headers=tester_headers)
        assert r.status_code == 403

    def test_public_read_only_allows_read_but_blocks_write(self, client, admin_headers):
        owner_id = _real_employee(client, admin_headers, "Account Owner RO")
        _, tester_headers = _employee_with_capabilities(
            client, admin_headers, ["accounts.read", "accounts.edit"], "Account Tester RO")
        account = client.post("/api/v1/accounts", json={
            "legal_name": "OWD RO Account", "owner_employee_id": owner_id,
        }, headers=admin_headers)
        aid = account.json()["id"]
        _set_owd(client, admin_headers, "ACCOUNT", "PUBLIC_READ_ONLY")

        r = client.get(f"/api/v1/accounts/{aid}", headers=tester_headers)
        assert r.status_code == 200

        r = client.patch(f"/api/v1/accounts/{aid}", json={"industry": "Changed"}, headers=tester_headers)
        assert r.status_code == 403

    def test_public_read_write_allows_read_and_write(self, client, admin_headers):
        owner_id = _real_employee(client, admin_headers, "Account Owner RW")
        _, tester_headers = _employee_with_capabilities(
            client, admin_headers, ["accounts.read", "accounts.edit"], "Account Tester RW")
        account = client.post("/api/v1/accounts", json={
            "legal_name": "OWD RW Account", "owner_employee_id": owner_id,
        }, headers=admin_headers)
        aid = account.json()["id"]
        _set_owd(client, admin_headers, "ACCOUNT", "PUBLIC_READ_WRITE")

        r = client.get(f"/api/v1/accounts/{aid}", headers=tester_headers)
        assert r.status_code == 200

        r = client.patch(f"/api/v1/accounts/{aid}", json={"industry": "Changed"}, headers=tester_headers)
        assert r.status_code == 200, r.text
        assert r.json()["industry"] == "Changed"


class TestOrgWideDefaultEnforcementOpportunity:
    def test_private_reproduces_todays_behavior(self, client, admin_headers):
        owner_id = _real_employee(client, admin_headers, "Opp Owner Private")
        account = client.post("/api/v1/accounts", json={"legal_name": "OWD Opp Private Account"},
                              headers=admin_headers).json()
        _, tester_headers = _employee_with_capabilities(
            client, admin_headers, ["opportunities.read", "opportunities.edit"], "Opp Tester Private")
        opp = client.post("/api/v1/opportunities", json={
            "account_id": account["id"], "name": "OWD Private Opp", "owner_employee_id": owner_id,
        }, headers=admin_headers)
        assert opp.status_code == 201, opp.text
        oid = opp.json()["id"]

        r = client.get(f"/api/v1/opportunities/{oid}", headers=tester_headers)
        assert r.status_code == 403

    def test_public_read_only_allows_read_but_blocks_write(self, client, admin_headers):
        owner_id = _real_employee(client, admin_headers, "Opp Owner RO")
        account = client.post("/api/v1/accounts", json={"legal_name": "OWD Opp RO Account"},
                              headers=admin_headers).json()
        _, tester_headers = _employee_with_capabilities(
            client, admin_headers, ["opportunities.read", "opportunities.edit"], "Opp Tester RO")
        opp = client.post("/api/v1/opportunities", json={
            "account_id": account["id"], "name": "OWD RO Opp", "owner_employee_id": owner_id,
        }, headers=admin_headers)
        oid = opp.json()["id"]
        _set_owd(client, admin_headers, "OPPORTUNITY", "PUBLIC_READ_ONLY")

        r = client.get(f"/api/v1/opportunities/{oid}", headers=tester_headers)
        assert r.status_code == 200

        r = client.patch(f"/api/v1/opportunities/{oid}", json={"next_step": "Changed"}, headers=tester_headers)
        assert r.status_code == 403

    def test_public_read_write_allows_read_and_write(self, client, admin_headers):
        owner_id = _real_employee(client, admin_headers, "Opp Owner RW")
        account = client.post("/api/v1/accounts", json={"legal_name": "OWD Opp RW Account"},
                              headers=admin_headers).json()
        _, tester_headers = _employee_with_capabilities(
            client, admin_headers, ["opportunities.read", "opportunities.edit"], "Opp Tester RW")
        opp = client.post("/api/v1/opportunities", json={
            "account_id": account["id"], "name": "OWD RW Opp", "owner_employee_id": owner_id,
        }, headers=admin_headers)
        oid = opp.json()["id"]
        _set_owd(client, admin_headers, "OPPORTUNITY", "PUBLIC_READ_WRITE")

        r = client.get(f"/api/v1/opportunities/{oid}", headers=tester_headers)
        assert r.status_code == 200

        r = client.patch(f"/api/v1/opportunities/{oid}", json={"next_step": "Changed"}, headers=tester_headers)
        assert r.status_code == 200, r.text
        assert r.json()["next_step"] == "Changed"


class TestRecordAccessIncludesRoleHierarchy:
    """The OWD/record-access model for LEAD/ACCOUNT/OPPORTUNITY includes Role
    Hierarchy as an additional access path (see services/
    record_access_service.py's module docstring) — a Director profile that
    is the parent of a Rep profile in Profile.parent_role_id sees the Rep's
    owned, PRIVATE Lead/Account/Opportunity purely through that hierarchy
    relationship, exactly as crm_service._hierarchy_scope() has always
    granted. OWD/sharing only ever widen this further, never narrow it — see
    test_profiles.py::TestRoleHierarchy.
    test_manager_sees_subordinates_row_but_not_a_sibling_holders for the
    equivalent hierarchy-only (no OWD/sharing involved) check this class
    complements."""

    def _employee_with_profile(self, client, admin_headers, profile_code, full_name):
        emp = client.post("/api/v1/admin/employees",
                          json={"email": f"owdhier.{uuid.uuid4().hex[:8]}@example.com", "full_name": full_name},
                          headers=admin_headers).json()
        client.put(f"/api/v1/admin/employees/{emp['id']}/profiles",
                  json={"profile_codes": [profile_code]}, headers=admin_headers)
        headers = {"Authorization": f"Bearer {mint_token_for_profiles(emp['id'], {profile_code})}"}
        return emp["id"], headers

    def _director_rep_sibling(self, client, admin_headers, capability_keys):
        director = _create_profile(client, admin_headers, display_name="OWD Director")
        rep = _create_profile(client, admin_headers, display_name="OWD Rep")
        sibling = _create_profile(client, admin_headers, display_name="OWD Sibling")
        client.patch(f"/api/v1/admin/profiles/{rep['id']}",
                    json={"parent_role_id": director["id"]}, headers=admin_headers)
        for p in (director, rep, sibling):
            client.put(f"/api/v1/admin/profiles/{p['id']}/capabilities",
                      json={"capability_keys": capability_keys}, headers=admin_headers)
        _, director_headers = self._employee_with_profile(client, admin_headers, director["code"], "OWD Director Emp")
        rep_id, rep_headers = self._employee_with_profile(client, admin_headers, rep["code"], "OWD Rep Emp")
        _, sibling_headers = self._employee_with_profile(client, admin_headers, sibling["code"], "OWD Sibling Emp")
        return rep_id, rep_headers, director_headers, sibling_headers

    def test_manager_sees_subordinates_private_lead(self, client, admin_headers):
        """User A (rep) owns a PRIVATE Lead. User B (director), higher in
        the Role Hierarchy, gets access through that relationship alone —
        the exact pre-OWD behavior, preserved as an additional path."""
        rep_id, rep_headers, director_headers, sibling_headers = self._director_rep_sibling(
            client, admin_headers, ["leads.read", "leads.create"])

        lead = client.post("/api/v1/leads", json={
            "company_name": "OWD Hierarchy Co", "contact_email": "test.lead@example.com", "last_name": "Singh", "owner_employee_id": rep_id,
        }, headers=rep_headers)
        assert lead.status_code == 201, lead.text
        lead_id = lead.json()["id"]

        r = client.get(f"/api/v1/leads/{lead_id}", headers=director_headers)
        assert r.status_code == 200  # subordinate-in-hierarchy grants access

        r = client.get(f"/api/v1/leads/{lead_id}", headers=sibling_headers)
        assert r.status_code == 403  # unrelated profile — never had access either way

        r = client.get(f"/api/v1/leads/{lead_id}", headers=rep_headers)
        assert r.status_code == 200  # owns it directly — ownership is unaffected

    def test_manager_sees_subordinates_private_account(self, client, admin_headers):
        rep_id, rep_headers, director_headers, _sibling_headers = self._director_rep_sibling(
            client, admin_headers, ["accounts.read", "accounts.create"])

        account = client.post("/api/v1/accounts", json={
            "legal_name": "OWD Hierarchy Account", "owner_employee_id": rep_id,
        }, headers=rep_headers)
        assert account.status_code == 201, account.text
        account_id = account.json()["id"]

        r = client.get(f"/api/v1/accounts/{account_id}", headers=director_headers)
        assert r.status_code == 200

    def test_manager_sees_subordinates_private_opportunity(self, client, admin_headers):
        rep_id, rep_headers, director_headers, _sibling_headers = self._director_rep_sibling(
            client, admin_headers, ["opportunities.read", "opportunities.create", "accounts.read", "accounts.create"])

        account = client.post("/api/v1/accounts", json={"legal_name": "OWD Hierarchy Opp Account"},
                              headers=rep_headers).json()
        opp = client.post("/api/v1/opportunities", json={
            "account_id": account["id"], "name": "OWD Hierarchy Opp", "owner_employee_id": rep_id,
        }, headers=rep_headers)
        assert opp.status_code == 201, opp.text
        opp_id = opp.json()["id"]

        r = client.get(f"/api/v1/opportunities/{opp_id}", headers=director_headers)
        assert r.status_code == 200

    def test_records_see_all_still_wins_regardless_of_hierarchy(
        self, client, admin_headers, leadership_headers,
    ):
        """records.see_all (a flat, non-hierarchy override) sees everything
        regardless of where the caller sits in the hierarchy, same as
        before this feature."""
        owner_id = _real_employee(client, admin_headers, "Hierarchy Removal Owner")
        lead = client.post("/api/v1/leads", json={
            "company_name": "OWD SeeAll Still Wins Co", "contact_email": "test.lead@example.com", "last_name": "Doe", "owner_employee_id": owner_id,
        }, headers=admin_headers)
        lead_id = lead.json()["id"]
        r = client.get(f"/api/v1/leads/{lead_id}", headers=leadership_headers)
        assert r.status_code == 200
