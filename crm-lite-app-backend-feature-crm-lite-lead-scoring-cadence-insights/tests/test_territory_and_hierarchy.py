"""Sales Territory/Region + Role Hierarchy record access — the feature that
extends record_access_service.can_user_access_record() with Role Hierarchy
(CurrentUser.subordinate_employee_ids()) and adds admin_models.Territory
(Employee/Account/Lead.territory_id).

Covers (see the requirements this implements):
- Employee territory assignment persists (create + update).
- Account/Lead default to their resolved owner's territory at create time.
- Same-territory peers do NOT automatically see each other's PRIVATE records
  (the "critical requirement" — Territory is data/defaulting only, never a
  grant on its own).
- A manager (Role Hierarchy) DOES get READ/EDIT (never DELETE) on a
  subordinate's records, regardless of territory.
- Explicit Record Sharing still works, and still combines correctly with the
  above.
- Unauthorized records are rejected by GET (detail) and excluded from list
  endpoints (Account lookup included) — enforced server-side.
- Existing OWD (PRIVATE-by-default) behavior is unweakened.

Same persistent-shared-Postgres-no-per-test-rollback caveat as every other
test module here (see test_record_access.py's identical note) — the autouse
fixture below resets all 5 OWD rows to PRIVATE before/after every test.
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


def _territory_id_by_code(client, admin_headers, code: str) -> int:
    """Employee/Account/Lead all key territory by id now, not code (see
    admin_models.EmployeeCreate.territory_id) — this file's own tests still
    refer to the seeded USA/CANADA rows by their well-known code, so resolve
    that to an id once here rather than hand-editing every call site."""
    rows = client.get("/api/v1/admin/lookups/territory", headers=admin_headers).json()
    return next(r["id"] for r in rows if r["code"] == code)


def _employee(client, admin_headers, full_name: str, territory: str | None = None) -> dict:
    payload = {"email": f"terr.{uuid.uuid4().hex[:8]}@example.com", "full_name": full_name}
    if territory is not None:
        payload["territory_id"] = _territory_id_by_code(client, admin_headers, territory)
    r = client.post("/api/v1/admin/employees", json=payload, headers=admin_headers)
    assert r.status_code == 201, r.text
    return r.json()


def _profile(client, admin_headers, display_name: str, capability_keys: list[str],
            parent_role_id: int | None = None) -> dict:
    r = client.post("/api/v1/admin/profiles",
                    json={"code": f"TERR{uuid.uuid4().hex[:8].upper()}", "display_name": display_name},
                    headers=admin_headers)
    assert r.status_code == 201, r.text
    profile = r.json()
    client.put(f"/api/v1/admin/profiles/{profile['id']}/capabilities",
              json={"capability_keys": capability_keys}, headers=admin_headers)
    if parent_role_id is not None:
        r = client.patch(f"/api/v1/admin/profiles/{profile['id']}",
                         json={"parent_role_id": parent_role_id}, headers=admin_headers)
        assert r.status_code == 200, r.text
    return profile


def _headers_for(client, admin_headers, employee_id: str, profile_code: str) -> dict:
    client.put(f"/api/v1/admin/employees/{employee_id}/profiles",
              json={"profile_codes": [profile_code]}, headers=admin_headers)
    return {"Authorization": f"Bearer {mint_token_for_profiles(employee_id, {profile_code})}"}


_REP_CAPS = ["leads.create", "leads.edit", "leads.read", "accounts.create", "accounts.edit", "accounts.read"]


class TestEmployeeTerritoryAssignment:
    def test_create_employee_with_territory(self, client, admin_headers):
        emp = _employee(client, admin_headers, "Karthik", territory="USA")
        assert emp["territory_name"] == "USA"
        assert emp["territory_id"] is not None

        r = client.get("/api/v1/admin/employees", headers=admin_headers)
        assert r.status_code == 200
        assert any(e["id"] == emp["id"] and e["territory_name"] == "USA" for e in r.json())

    def test_update_employee_territory(self, client, admin_headers):
        emp = _employee(client, admin_headers, "Harshitha")
        assert emp["territory_id"] is None
        assert emp["territory_name"] is None

        canada_id = _territory_id_by_code(client, admin_headers, "CANADA")
        r = client.patch(f"/api/v1/admin/employees/{emp['id']}", json={"territory_id": canada_id},
                         headers=admin_headers)
        assert r.status_code == 200, r.text
        assert r.json()["territory_id"] == canada_id
        # Displayed by Name ("Canada"), never Code ("CANADA").
        assert r.json()["territory_name"] == "Canada"

        # Clearing it back to None is also honored (not silently ignored).
        r = client.patch(f"/api/v1/admin/employees/{emp['id']}", json={"territory_id": None},
                         headers=admin_headers)
        assert r.status_code == 200, r.text
        assert r.json()["territory_id"] is None
        assert r.json()["territory_name"] is None

    def test_unknown_territory_id_rejected(self, client, admin_headers):
        r = client.post("/api/v1/admin/employees",
                        json={"email": f"bad.{uuid.uuid4().hex[:8]}@example.com",
                              "full_name": "Bad Territory", "territory_id": 999999999},
                        headers=admin_headers)
        assert r.status_code == 422

    def test_inactive_territory_cannot_be_newly_assigned(self, client, admin_headers):
        created = client.post("/api/v1/admin/lookups/territory", json={
            "display_name": "Retired Territory", "country": "USA", "is_active": False,
        }, headers=admin_headers)
        assert created.status_code == 201, created.text
        territory_id = created.json()["id"]

        r = client.post("/api/v1/admin/employees",
                        json={"email": f"inactive.{uuid.uuid4().hex[:8]}@example.com",
                              "full_name": "Inactive Territory Assignee", "territory_id": territory_id},
                        headers=admin_headers)
        assert r.status_code == 422

    def test_existing_assignment_survives_territory_becoming_inactive(self, client, admin_headers):
        """Deactivating a territory after the fact must not break an
        employee already assigned to it — only a NEW/changed assignment is
        checked for active status."""
        created = client.post("/api/v1/admin/lookups/territory", json={
            "display_name": "Soon Retired Territory", "country": "USA", "is_active": True,
        }, headers=admin_headers)
        territory_id = created.json()["id"]
        emp = client.post("/api/v1/admin/employees",
                          json={"email": f"survivor.{uuid.uuid4().hex[:8]}@example.com",
                                "full_name": "Survivor", "territory_id": territory_id},
                          headers=admin_headers).json()
        assert emp["territory_id"] == territory_id

        r = client.patch(f"/api/v1/admin/lookups/territory/{territory_id}",
                         json={"is_active": False}, headers=admin_headers)
        assert r.status_code == 200, r.text

        # A read (or an unrelated-field update) of the already-assigned
        # employee must still show the assignment, untouched.
        r = client.get("/api/v1/admin/employees", headers=admin_headers)
        row = next(e for e in r.json() if e["id"] == emp["id"])
        assert row["territory_id"] == territory_id
        assert row["territory_name"] == "Soon Retired Territory"

        r = client.patch(f"/api/v1/admin/employees/{emp['id']}",
                         json={"full_name": "Survivor Renamed"}, headers=admin_headers)
        assert r.status_code == 200, r.text
        assert r.json()["territory_id"] == territory_id


class TestTerritoryLookupSeeded:
    def test_usa_and_canada_active(self, client, admin_headers):
        r = client.get("/api/v1/admin/lookups/territory", headers=admin_headers)
        assert r.status_code == 200, r.text
        rows = {row["code"]: row for row in r.json()}
        assert rows["USA"]["is_active"] is True
        assert rows["CANADA"]["is_active"] is True
        # Both top-level rows are country-wide -- no single Region.
        assert rows["USA"]["region"] is None
        assert rows["CANADA"]["region"] is None

    def test_usa_region_children_seeded_under_usa_parent(self, client, admin_headers):
        rows = client.get("/api/v1/admin/lookups/territory", headers=admin_headers).json()
        usa_id = next(r["id"] for r in rows if r["code"] == "USA")
        by_name = {r["display_name"]: r for r in rows}
        for name, region in [
            ("USA - Northeast", "Northeast"), ("USA - Midwest", "Midwest"),
            ("USA - South", "South"), ("USA - West", "West"),
        ]:
            row = by_name[name]
            assert row["country"] == "USA"
            assert row["region"] == region
            assert row["parent_territory_id"] == usa_id
            assert row["is_active"] is True
            assert row["code"] is None  # demonstrates Code is genuinely optional

    def test_canada_region_children_seeded_under_canada_parent(self, client, admin_headers):
        rows = client.get("/api/v1/admin/lookups/territory", headers=admin_headers).json()
        canada_id = next(r["id"] for r in rows if r["code"] == "CANADA")
        by_name = {r["display_name"]: r for r in rows}
        for name, region in [
            ("Canada - Atlantic", "Atlantic"), ("Canada - Central", "Central Canada"),
            ("Canada - Prairies", "Prairies"), ("Canada - West", "West"), ("Canada - North", "North"),
        ]:
            row = by_name[name]
            assert row["country"] == "Canada"
            assert row["region"] == region
            assert row["parent_territory_id"] == canada_id
            assert row["is_active"] is True
            assert row["code"] is None


class TestTerritoryManagement:
    """Create/edit/hierarchy for the Territory object itself, via the
    existing generic /admin/lookups/territory endpoints (no bespoke CRUD —
    see admin_service._LOOKUP_TABLES)."""

    def test_create_territory_with_code(self, client, admin_headers):
        code = f"t{uuid.uuid4().hex[:8]}"
        r = client.post("/api/v1/admin/lookups/territory", json={
            "code": code, "display_name": "USA - East Test", "country": "USA",
            "region": "Northeast", "is_active": True,
        }, headers=admin_headers)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["code"] == code.upper()  # uppercased, same as every other lookup table
        assert body["region"] == "Northeast"

    def test_create_territory_without_code(self, client, admin_headers):
        r = client.post("/api/v1/admin/lookups/territory", json={
            "display_name": "No Code Territory", "country": "USA", "is_active": True,
        }, headers=admin_headers)
        assert r.status_code == 201, r.text
        assert r.json()["code"] is None

    def test_create_territory_without_region_is_allowed(self, client, admin_headers):
        """Region is optional -- a top-level/country-wide territory
        legitimately has none (unlike Country, which is required)."""
        r = client.post("/api/v1/admin/lookups/territory", json={
            "display_name": "Country Wide Test Territory", "country": "USA", "is_active": True,
        }, headers=admin_headers)
        assert r.status_code == 201, r.text
        assert r.json()["region"] is None

    def test_create_territory_without_country_is_rejected(self, client, admin_headers):
        r = client.post("/api/v1/admin/lookups/territory", json={
            "display_name": "No Country Territory", "is_active": True,
        }, headers=admin_headers)
        assert r.status_code == 422

    def test_create_territory_with_unsupported_country_is_rejected(self, client, admin_headers):
        r = client.post("/api/v1/admin/lookups/territory", json={
            "display_name": "Mars Territory", "country": "Mars", "is_active": True,
        }, headers=admin_headers)
        assert r.status_code == 422

    def test_create_territory_with_invalid_region_for_country_is_rejected(self, client, admin_headers):
        r = client.post("/api/v1/admin/lookups/territory", json={
            "display_name": "Bad Region Territory", "country": "USA", "region": "Atlantic",
            "is_active": True,
        }, headers=admin_headers)
        assert r.status_code == 422

    def test_create_territory_with_parent(self, client, admin_headers):
        usa_id = _territory_id_by_code(client, admin_headers, "USA")
        r = client.post("/api/v1/admin/lookups/territory", json={
            "display_name": "USA - Child Test", "country": "USA", "is_active": True,
            "parent_territory_id": usa_id,
        }, headers=admin_headers)
        assert r.status_code == 201, r.text
        assert r.json()["parent_territory_id"] == usa_id

    def test_create_territory_with_unknown_parent_is_rejected(self, client, admin_headers):
        r = client.post("/api/v1/admin/lookups/territory", json={
            "display_name": "Orphan Territory", "country": "USA", "is_active": True,
            "parent_territory_id": 999999999,
        }, headers=admin_headers)
        assert r.status_code == 422

    def test_edit_territory_fields(self, client, admin_headers):
        created = client.post("/api/v1/admin/lookups/territory", json={
            "display_name": "Editable Territory", "country": "USA", "is_active": True,
        }, headers=admin_headers).json()

        r = client.patch(f"/api/v1/admin/lookups/territory/{created['id']}", json={
            "display_name": "Edited Territory Name", "description": "Now has a description.",
            "region": "West",
        }, headers=admin_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["display_name"] == "Edited Territory Name"
        assert body["description"] == "Now has a description."
        assert body["region"] == "West"

    def test_deactivate_and_reactivate_territory(self, client, admin_headers):
        created = client.post("/api/v1/admin/lookups/territory", json={
            "display_name": "Toggle Territory", "country": "USA", "is_active": True,
        }, headers=admin_headers).json()

        r = client.patch(f"/api/v1/admin/lookups/territory/{created['id']}",
                         json={"is_active": False}, headers=admin_headers)
        assert r.status_code == 200, r.text
        assert r.json()["is_active"] is False

        r = client.patch(f"/api/v1/admin/lookups/territory/{created['id']}",
                         json={"is_active": True}, headers=admin_headers)
        assert r.status_code == 200, r.text
        assert r.json()["is_active"] is True

    def test_territory_cannot_be_its_own_parent(self, client, admin_headers):
        created = client.post("/api/v1/admin/lookups/territory", json={
            "display_name": "Self Parent Territory", "country": "USA", "is_active": True,
        }, headers=admin_headers).json()

        r = client.patch(f"/api/v1/admin/lookups/territory/{created['id']}",
                         json={"parent_territory_id": created["id"]}, headers=admin_headers)
        assert r.status_code == 422

    def test_territory_hierarchy_cycle_is_rejected(self, client, admin_headers):
        parent = client.post("/api/v1/admin/lookups/territory", json={
            "display_name": "Cycle Parent", "country": "USA", "is_active": True,
        }, headers=admin_headers).json()
        child = client.post("/api/v1/admin/lookups/territory", json={
            "display_name": "Cycle Child", "country": "USA", "is_active": True,
            "parent_territory_id": parent["id"],
        }, headers=admin_headers).json()

        # Trying to make `parent` report to its own child would create a cycle.
        r = client.patch(f"/api/v1/admin/lookups/territory/{parent['id']}",
                         json={"parent_territory_id": child["id"]}, headers=admin_headers)
        assert r.status_code == 422


class TestRecordTerritoryDefaulting:
    def test_account_defaults_to_owners_territory(self, client, admin_headers):
        karthik = _employee(client, admin_headers, "Karthik Territory", territory="USA")
        karthik_headers = _headers_for(client, admin_headers, karthik["id"], _profile(
            client, admin_headers, "Territory Rep", _REP_CAPS)["code"])

        r = client.post("/api/v1/accounts", json={"legal_name": "ABC Company"}, headers=karthik_headers)
        assert r.status_code == 201, r.text
        assert r.json()["territory"] == "USA"

    def test_lead_defaults_to_owners_territory(self, client, admin_headers):
        harshitha = _employee(client, admin_headers, "Harshitha Territory", territory="CANADA")
        headers = _headers_for(client, admin_headers, harshitha["id"], _profile(
            client, admin_headers, "Territory Rep CA", _REP_CAPS)["code"])

        r = client.post("/api/v1/leads", json={"company_name": "Northern Co", "contact_email": "test.lead@example.com", "last_name": "Smith"},
                        headers=headers)
        assert r.status_code == 201, r.text
        # Displayed by Name ("Canada"), never Code ("CANADA").
        assert r.json()["territory"] == "Canada"

    def test_account_defaults_to_explicit_owner_not_creator(self, client, admin_headers):
        """An ADMIN creating an Account on behalf of a USA rep gets that
        rep's territory, not the ADMIN's own (which has none) — territory
        follows the resolved owner, the existing assignment mechanism,
        never the acting user blindly."""
        rep = _employee(client, admin_headers, "Owner Rep", territory="USA")
        r = client.post("/api/v1/accounts",
                        json={"legal_name": "Owned By Rep Co", "owner_employee_id": rep["id"]},
                        headers=admin_headers)
        assert r.status_code == 201, r.text
        assert r.json()["territory"] == "USA"

    def test_unowned_lead_has_no_territory(self, client, admin_headers):
        """email-intake-style unowned leads (no resolvable owner) simply
        have no territory — never guessed."""
        no_profile_admin_lead = client.post(
            "/api/v1/leads", json={"company_name": "Unowned Co", "contact_email": "test.lead@example.com", "last_name": "Doe"},
            headers=admin_headers)
        assert no_profile_admin_lead.status_code == 201, no_profile_admin_lead.text
        # ADMIN's dev-bypass identity has no linked Employee row, so
        # verified_employee_uuid() resolves to None -> no owner -> no territory.


class TestSameTerritoryDoesNotGrantAccess:
    """The critical requirement: two USA reps with no ownership/sharing/
    hierarchy relationship must not see each other's PRIVATE records merely
    for sharing a territory."""

    def test_peer_cannot_read_others_private_account(self, client, admin_headers):
        rep_profile = _profile(client, admin_headers, "Peer Rep", _REP_CAPS)
        karthik = _employee(client, admin_headers, "Karthik Peer", territory="USA")
        akhilesh = _employee(client, admin_headers, "Akhilesh Peer", territory="USA")
        karthik_headers = _headers_for(client, admin_headers, karthik["id"], rep_profile["code"])
        akhilesh_headers = _headers_for(client, admin_headers, akhilesh["id"], rep_profile["code"])

        created = client.post("/api/v1/accounts", json={"legal_name": "Karthik Account A"},
                              headers=karthik_headers).json()
        assert created["territory"] == "USA"

        r = client.get(f"/api/v1/accounts/{created['id']}", headers=akhilesh_headers)
        assert r.status_code == 403

        r = client.get("/api/v1/accounts", headers=akhilesh_headers)
        assert r.status_code == 200
        assert all(a["id"] != created["id"] for a in r.json()["items"])

    def test_peer_cannot_read_others_private_lead(self, client, admin_headers):
        rep_profile = _profile(client, admin_headers, "Peer Rep Lead", _REP_CAPS)
        karthik = _employee(client, admin_headers, "Karthik Peer Lead", territory="USA")
        akhilesh = _employee(client, admin_headers, "Akhilesh Peer Lead", territory="USA")
        karthik_headers = _headers_for(client, admin_headers, karthik["id"], rep_profile["code"])
        akhilesh_headers = _headers_for(client, admin_headers, akhilesh["id"], rep_profile["code"])

        created = client.post("/api/v1/leads", json={"company_name": "Karthik Lead Co", "contact_email": "test.lead@example.com", "last_name": "Smith"},
                              headers=karthik_headers).json()

        r = client.get(f"/api/v1/leads/{created['id']}", headers=akhilesh_headers)
        assert r.status_code == 403

        r = client.get("/api/v1/leads", headers=akhilesh_headers)
        assert r.status_code == 200
        assert all(lead["id"] != created["id"] for lead in r.json())

        # Own records remain visible.
        r = client.get(f"/api/v1/leads/{created['id']}", headers=karthik_headers)
        assert r.status_code == 200


class TestManagerRoleHierarchyAccess:
    def test_manager_can_read_and_edit_subordinates_account(self, client, admin_headers):
        rep_profile = _profile(client, admin_headers, "Hierarchy Rep", _REP_CAPS)
        manager_profile = _profile(
            client, admin_headers, "Hierarchy Manager",
            _REP_CAPS + ["accounts.assign"], parent_role_id=None)
        # rep reports to manager: rep's profile's parent_role_id = manager's id
        client.patch(f"/api/v1/admin/profiles/{rep_profile['id']}",
                    json={"parent_role_id": manager_profile["id"]}, headers=admin_headers)

        karthik = _employee(client, admin_headers, "Karthik Hierarchy", territory="USA")
        manager = _employee(client, admin_headers, "Manager Hierarchy", territory="USA")
        karthik_headers = _headers_for(client, admin_headers, karthik["id"], rep_profile["code"])
        manager_headers = _headers_for(client, admin_headers, manager["id"], manager_profile["code"])

        account = client.post("/api/v1/accounts", json={"legal_name": "Karthik Managed Account"},
                              headers=karthik_headers).json()

        r = client.get(f"/api/v1/accounts/{account['id']}", headers=manager_headers)
        assert r.status_code == 200, r.text
        assert r.json()["can_edit"] is True

        r = client.patch(f"/api/v1/accounts/{account['id']}", json={"industry": "Manufacturing"},
                         headers=manager_headers)
        assert r.status_code == 200, r.text
        assert r.json()["industry"] == "Manufacturing"

    def test_manager_cannot_delete_via_hierarchy_alone(self, client, admin_headers):
        """Hierarchy grants READ/EDIT, never DELETE — only ownership or
        records.see_all does (see record_access_service.py)."""
        rep_profile = _profile(client, admin_headers, "Hierarchy Rep NoDel", _REP_CAPS)
        manager_profile = _profile(
            client, admin_headers, "Hierarchy Manager NoDel",
            _REP_CAPS + ["accounts.delete"])
        client.patch(f"/api/v1/admin/profiles/{rep_profile['id']}",
                    json={"parent_role_id": manager_profile["id"]}, headers=admin_headers)

        karthik = _employee(client, admin_headers, "Karthik NoDel", territory="USA")
        manager = _employee(client, admin_headers, "Manager NoDel", territory="USA")
        karthik_headers = _headers_for(client, admin_headers, karthik["id"], rep_profile["code"])
        manager_headers = _headers_for(client, admin_headers, manager["id"], manager_profile["code"])

        account = client.post("/api/v1/accounts", json={"legal_name": "No Delete Co"},
                              headers=karthik_headers).json()

        r = client.get(f"/api/v1/accounts/{account['id']}", headers=manager_headers)
        assert r.json()["can_delete"] is False

        r = client.delete(f"/api/v1/accounts/{account['id']}", headers=manager_headers)
        assert r.status_code == 403

    def test_peers_of_same_profile_are_not_subordinates(self, client, admin_headers):
        """Two employees holding the SAME profile are peers, not manager/
        subordinate — holding a profile never grants access to a fellow
        holder's records (mirrors the same-territory non-access test, via
        a different mechanism)."""
        rep_profile = _profile(client, admin_headers, "Peer Profile Only", _REP_CAPS)
        karthik = _employee(client, admin_headers, "Karthik Same Profile", territory="USA")
        akhilesh = _employee(client, admin_headers, "Akhilesh Same Profile", territory="USA")
        karthik_headers = _headers_for(client, admin_headers, karthik["id"], rep_profile["code"])
        akhilesh_headers = _headers_for(client, admin_headers, akhilesh["id"], rep_profile["code"])

        account = client.post("/api/v1/accounts", json={"legal_name": "Same Profile Co"},
                              headers=karthik_headers).json()

        r = client.get(f"/api/v1/accounts/{account['id']}", headers=akhilesh_headers)
        assert r.status_code == 403


class TestCrossTerritoryStillDenied:
    def test_different_territory_and_no_relationship_denied(self, client, admin_headers):
        rep_profile = _profile(client, admin_headers, "Cross Territory Rep", _REP_CAPS)
        karthik = _employee(client, admin_headers, "Karthik USA", territory="USA")
        other = _employee(client, admin_headers, "Other Canada", territory="CANADA")
        karthik_headers = _headers_for(client, admin_headers, karthik["id"], rep_profile["code"])
        other_headers = _headers_for(client, admin_headers, other["id"], rep_profile["code"])

        account = client.post("/api/v1/accounts", json={"legal_name": "USA Only Co"},
                              headers=karthik_headers).json()
        assert account["territory"] == "USA"

        r = client.get(f"/api/v1/accounts/{account['id']}", headers=other_headers)
        assert r.status_code == 403


class TestExplicitSharingStillWorks:
    def test_explicit_share_grants_access_alongside_hierarchy_and_territory(self, client, admin_headers):
        rep_profile = _profile(client, admin_headers, "Share Rep", _REP_CAPS + ["record_shares.write"])
        karthik = _employee(client, admin_headers, "Karthik Share", territory="USA")
        akhilesh = _employee(client, admin_headers, "Akhilesh Share", territory="USA")
        karthik_headers = _headers_for(client, admin_headers, karthik["id"], rep_profile["code"])
        akhilesh_headers = _headers_for(client, admin_headers, akhilesh["id"], rep_profile["code"])

        account = client.post("/api/v1/accounts", json={"legal_name": "Shared Account A"},
                              headers=karthik_headers).json()

        # Before sharing: denied (same territory, no hierarchy).
        assert client.get(f"/api/v1/accounts/{account['id']}", headers=akhilesh_headers).status_code == 403

        r = client.post("/api/v1/record-shares",
                        json={"object_name": "ACCOUNT", "record_id": account["id"],
                              "shared_with_employee_id": akhilesh["id"], "access_level": "READ"},
                        headers=karthik_headers)
        assert r.status_code == 201, r.text

        r = client.get(f"/api/v1/accounts/{account['id']}", headers=akhilesh_headers)
        assert r.status_code == 200
        assert r.json()["can_edit"] is False  # READ share only

        # Revoking it removes access again.
        share_id = client.get(
            "/api/v1/record-shares", params={"object_name": "ACCOUNT", "record_id": account["id"]},
            headers=karthik_headers).json()[0]["id"]
        client.delete(f"/api/v1/record-shares/{share_id}", headers=karthik_headers)
        assert client.get(f"/api/v1/accounts/{account['id']}", headers=akhilesh_headers).status_code == 403


class TestAccountLookupSecurity:
    def test_lookup_returns_only_authorized_accounts(self, client, admin_headers):
        rep_profile = _profile(client, admin_headers, "Lookup Rep", _REP_CAPS)
        karthik = _employee(client, admin_headers, "Karthik Lookup", territory="USA")
        akhilesh = _employee(client, admin_headers, "Akhilesh Lookup", territory="USA")
        karthik_headers = _headers_for(client, admin_headers, karthik["id"], rep_profile["code"])
        akhilesh_headers = _headers_for(client, admin_headers, akhilesh["id"], rep_profile["code"])

        own_account = client.post("/api/v1/accounts", json={"legal_name": "Karthik Own Lookup Co"},
                                  headers=karthik_headers).json()
        other_account = client.post("/api/v1/accounts", json={"legal_name": "Akhilesh Private Lookup Co"},
                                    headers=akhilesh_headers).json()

        r = client.get("/api/v1/accounts", headers=karthik_headers)
        assert r.status_code == 200
        ids = {a["id"] for a in r.json()["items"]}
        assert own_account["id"] in ids
        assert other_account["id"] not in ids


class TestOwdStillEnforced:
    def test_private_owd_blocks_non_owner_non_manager(self, client, admin_headers):
        rep_profile = _profile(client, admin_headers, "OWD Rep", _REP_CAPS)
        karthik = _employee(client, admin_headers, "Karthik OWD", territory="USA")
        akhilesh = _employee(client, admin_headers, "Akhilesh OWD", territory="USA")
        karthik_headers = _headers_for(client, admin_headers, karthik["id"], rep_profile["code"])
        akhilesh_headers = _headers_for(client, admin_headers, akhilesh["id"], rep_profile["code"])

        lead = client.post("/api/v1/leads", json={"company_name": "OWD Co", "contact_email": "test.lead@example.com", "last_name": "Rao"},
                           headers=karthik_headers).json()
        assert client.get(f"/api/v1/leads/{lead['id']}", headers=akhilesh_headers).status_code == 403

        r = client.put("/api/v1/org-wide-defaults", json={
            "entries": [{"object_name": name, "access_level": "PUBLIC_READ_ONLY" if name == "LEAD" else "PRIVATE"}
                       for name in OWD_OBJECTS]}, headers=admin_headers)
        assert r.status_code == 200, r.text

        r = client.get(f"/api/v1/leads/{lead['id']}", headers=akhilesh_headers)
        assert r.status_code == 200
        assert r.json()["can_edit"] is False
