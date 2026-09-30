"""Profiles — admin-configurable object-level access. Replaces the old fixed
CAPABILITIES dict: which capability keys (utils.permissions.CAPABILITY_
REGISTRY) a Profile grants now lives in the role_capability table, edited
via /admin/profiles/{id}/capabilities. See admin_models.Profile's docstring
and utils/permissions.py.

This is a persistent, shared Postgres DB with no per-test rollback — tests
that create a profile use a unique code (uuid suffix) so they don't collide.
"""
import uuid

from src.repositories.admin_repository import get_profile_repository
from src.services.auth_service import mint_token_for_profiles


def _unique_code() -> str:
    return f"TESTPROFILE{uuid.uuid4().hex[:8].upper()}"


def _create_profile(client, admin_headers, code=None, display_name="Test Profile") -> dict:
    payload = {"code": code or _unique_code(), "display_name": display_name}
    r = client.post("/api/v1/admin/profiles", json=payload, headers=admin_headers)
    assert r.status_code == 201, r.text
    return r.json()


class TestProfileCrud:
    def test_non_admin_cannot_manage_profiles(self, client, sales_headers, leadership_headers):
        r = client.get("/api/v1/admin/profiles", headers=sales_headers)
        assert r.status_code == 403
        r = client.post("/api/v1/admin/profiles", json={"code": "X", "display_name": "X"},
                        headers=leadership_headers)
        assert r.status_code == 403

    def test_create_list_update(self, client, admin_headers):
        created = _create_profile(client, admin_headers, display_name="Support Rep")
        assert created["is_system"] is False

        r = client.get("/api/v1/admin/profiles", headers=admin_headers)
        assert r.status_code == 200
        assert any(p["id"] == created["id"] for p in r.json())

        r = client.patch(f"/api/v1/admin/profiles/{created['id']}",
                         json={"display_name": "Support Rep (Renamed)"}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["display_name"] == "Support Rep (Renamed)"

    def test_duplicate_code_is_rejected(self, client, admin_headers):
        code = _unique_code()
        _create_profile(client, admin_headers, code=code)
        r = client.post("/api/v1/admin/profiles", json={"code": code, "display_name": "Dup"},
                        headers=admin_headers)
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "PROFILE_CODE_TAKEN"

    def test_the_4_seeded_profiles_are_system_protected(self, client, admin_headers):
        r = client.get("/api/v1/admin/profiles", headers=admin_headers)
        seeded = {p["code"]: p for p in r.json() if p["code"] in
                 {"SALES", "ACCOUNT_EXEC", "LEADERSHIP", "ADMIN"}}
        assert len(seeded) == 4
        assert all(p["is_system"] for p in seeded.values())

        admin_profile_id = seeded["ADMIN"]["id"]
        r = client.delete(f"/api/v1/admin/profiles/{admin_profile_id}", headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "PROFILE_IS_SYSTEM"

    def test_non_admin_system_profile_can_be_deleted_once_unassigned(self, client, admin_headers):
        """Only ADMIN is permanently protected (see admin_service.delete_
        profile's docstring comment) — any other profile marked is_system
        can be deleted like a custom one, once nothing still holds it. Flips
        is_system directly via the repository (no API creates an is_system
        profile) to exercise this exact boundary without touching the real
        seeded SALES/ACCOUNT_EXEC/LEADERSHIP rows in this shared DB."""
        profile = _create_profile(client, admin_headers)
        get_profile_repository().update(profile["id"], is_system=True)

        r = client.delete(f"/api/v1/admin/profiles/{profile['id']}", headers=admin_headers)
        assert r.status_code == 204

        r = client.get("/api/v1/admin/profiles", headers=admin_headers)
        assert all(p["id"] != profile["id"] for p in r.json())

    def test_delete_blocked_while_assigned_then_allowed_once_freed(self, client, admin_headers):
        profile = _create_profile(client, admin_headers)
        emp = client.post("/api/v1/admin/employees",
                          json={"email": f"profiletest.{uuid.uuid4().hex[:8]}@example.com",
                               "full_name": "Profile Test Rep"},
                          headers=admin_headers).json()
        r = client.put(f"/api/v1/admin/employees/{emp['id']}/profiles",
                       json={"profile_codes": [profile["code"]]}, headers=admin_headers)
        assert r.status_code == 200

        r = client.delete(f"/api/v1/admin/profiles/{profile['id']}", headers=admin_headers)
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "PROFILE_IN_USE"

        client.put(f"/api/v1/admin/employees/{emp['id']}/profiles",
                  json={"profile_codes": []}, headers=admin_headers)
        r = client.delete(f"/api/v1/admin/profiles/{profile['id']}", headers=admin_headers)
        assert r.status_code == 204


class TestCapabilityRegistry:
    def test_list_capabilities_includes_records_see_all(self, client, admin_headers):
        r = client.get("/api/v1/admin/capabilities", headers=admin_headers)
        assert r.status_code == 200
        keys = {c["key"] for c in r.json()}
        assert "records.see_all" in keys
        assert "audit.see_all" in keys
        assert "leads.write" in keys


class TestProfileCapabilities:
    def test_new_profile_starts_with_zero_capabilities(self, client, admin_headers):
        profile = _create_profile(client, admin_headers)
        r = client.get(f"/api/v1/admin/profiles/{profile['id']}/capabilities", headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["capability_keys"] == []

    def test_save_grants_exactly_the_submitted_set(self, client, admin_headers):
        profile = _create_profile(client, admin_headers)
        r = client.put(f"/api/v1/admin/profiles/{profile['id']}/capabilities",
                       json={"capability_keys": ["leads.write", "platform.read"]}, headers=admin_headers)
        assert r.status_code == 200
        assert set(r.json()["capability_keys"]) == {"leads.write", "platform.read"}

        r = client.put(f"/api/v1/admin/profiles/{profile['id']}/capabilities",
                       json={"capability_keys": ["platform.read"]}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["capability_keys"] == ["platform.read"]  # leads.write revoked, not accumulated

    def test_rejects_unknown_capability_key(self, client, admin_headers):
        profile = _create_profile(client, admin_headers)
        r = client.put(f"/api/v1/admin/profiles/{profile['id']}/capabilities",
                       json={"capability_keys": ["not.a.real.capability"]}, headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "CAPABILITY_NOT_ELIGIBLE"

    def test_cannot_restrict_the_admin_profile(self, client, admin_headers):
        r = client.get("/api/v1/admin/profiles", headers=admin_headers)
        admin_profile_id = next(p["id"] for p in r.json() if p["code"] == "ADMIN")
        r = client.put(f"/api/v1/admin/profiles/{admin_profile_id}/capabilities",
                       json={"capability_keys": ["platform.read"]}, headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "CANNOT_RESTRICT_ADMIN_PROFILE"


class TestEndToEndEnforcement:
    """A freshly created, zero-capability profile really can't do anything
    until an admin grants it a capability — the default-deny guarantee."""

    def test_zero_capability_profile_is_forbidden_then_granted_access(self, client, admin_headers):
        profile = _create_profile(client, admin_headers)
        emp = client.post("/api/v1/admin/employees",
                          json={"email": f"zerocap.{uuid.uuid4().hex[:8]}@example.com",
                               "full_name": "Zero Cap Rep"},
                          headers=admin_headers).json()
        client.put(f"/api/v1/admin/employees/{emp['id']}/profiles",
                  json={"profile_codes": [profile["code"]]}, headers=admin_headers)
        headers = {"Authorization": f"Bearer {mint_token_for_profiles(emp['id'], {profile['code']})}"}

        r = client.get("/api/v1/leads", headers=headers)
        assert r.status_code == 403

        client.put(f"/api/v1/admin/profiles/{profile['id']}/capabilities",
                  json={"capability_keys": ["leads.read"]}, headers=admin_headers)
        headers = {"Authorization": f"Bearer {mint_token_for_profiles(emp['id'], {profile['code']})}"}

        r = client.get("/api/v1/leads", headers=headers)
        assert r.status_code == 200

    def test_records_see_all_capability_drives_row_scoping(self, client, admin_headers):
        """A profile with leads.read + leads.create but WITHOUT
        records.see_all should be scoped to owned rows only, same as SALES —
        proving the row-scoping check reads the same capability mechanism as
        the route gate, not a separate hardcoded tuple."""
        profile = _create_profile(client, admin_headers)
        client.put(f"/api/v1/admin/profiles/{profile['id']}/capabilities",
                  json={"capability_keys": ["leads.read", "leads.create"]}, headers=admin_headers)
        emp = client.post("/api/v1/admin/employees",
                          json={"email": f"scopetest.{uuid.uuid4().hex[:8]}@example.com",
                               "full_name": "Scope Test Rep"},
                          headers=admin_headers).json()
        client.put(f"/api/v1/admin/employees/{emp['id']}/profiles",
                  json={"profile_codes": [profile["code"]]}, headers=admin_headers)
        headers = {"Authorization": f"Bearer {mint_token_for_profiles(emp['id'], {profile['code']})}"}

        owned = client.post("/api/v1/leads", json={
            "company_name": "Scoped Co", "contact_email": "test.lead@example.com", "last_name": "Rao", "owner_employee_id": emp["id"],
        }, headers=headers)
        assert owned.status_code == 201, owned.text

        other = client.post("/api/v1/leads", json={
            "company_name": "Unowned Co", "contact_email": "test.lead@example.com", "last_name": "Iyer",
        }, headers=admin_headers)
        assert other.status_code == 201

        r = client.get(f"/api/v1/leads/{other.json()['id']}", headers=headers)
        assert r.status_code == 403  # not owned, and no records.see_all
        r = client.get(f"/api/v1/leads/{owned.json()['id']}", headers=headers)
        assert r.status_code == 200  # owned


class TestRoleHierarchy:
    """Role Hierarchy — an admin-configurable parent/child tree among
    Profiles (Profile.parent_role_id), CurrentUser.subordinate_employee_ids(),
    and crm_service._hierarchy_scope(). Holding a profile grants visibility
    into rows owned by anyone holding a profile strictly beneath it — for
    LEAD/ACCOUNT/CONTACT/OPPORTUNITY/CAMPAIGN this is now expressed via
    services/record_access_service.py's own hierarchy check (an additional
    path alongside the newer OWD/sharing layers, never a replacement for
    it — see that module's docstring), and for every OTHER module
    (Agreement/Project/SOW/Communications) via the separate, untouched
    src/utils/scope.py."""

    def test_self_parent_is_rejected(self, client, admin_headers):
        profile = _create_profile(client, admin_headers)
        r = client.patch(f"/api/v1/admin/profiles/{profile['id']}",
                         json={"parent_role_id": profile["id"]}, headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "PROFILE_HIERARCHY_CYCLE"

    def test_nonexistent_parent_is_rejected(self, client, admin_headers):
        profile = _create_profile(client, admin_headers)
        r = client.patch(f"/api/v1/admin/profiles/{profile['id']}",
                         json={"parent_role_id": 999999}, headers=admin_headers)
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "PROFILE_NOT_FOUND"

    def test_cycle_is_rejected(self, client, admin_headers):
        a = _create_profile(client, admin_headers)
        b = _create_profile(client, admin_headers)
        # b reports to a
        r = client.patch(f"/api/v1/admin/profiles/{b['id']}",
                         json={"parent_role_id": a["id"]}, headers=admin_headers)
        assert r.status_code == 200
        # a reporting to b would close the loop
        r = client.patch(f"/api/v1/admin/profiles/{a['id']}",
                         json={"parent_role_id": b["id"]}, headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "PROFILE_HIERARCHY_CYCLE"

    def test_set_and_clear_parent(self, client, admin_headers):
        a = _create_profile(client, admin_headers)
        b = _create_profile(client, admin_headers)
        r = client.patch(f"/api/v1/admin/profiles/{b['id']}",
                         json={"parent_role_id": a["id"]}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["parent_role_id"] == a["id"]

        r = client.patch(f"/api/v1/admin/profiles/{b['id']}",
                         json={"parent_role_id": None}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["parent_role_id"] is None

    def test_delete_blocked_while_a_parent(self, client, admin_headers):
        a = _create_profile(client, admin_headers)
        b = _create_profile(client, admin_headers)
        client.patch(f"/api/v1/admin/profiles/{b['id']}",
                    json={"parent_role_id": a["id"]}, headers=admin_headers)
        r = client.delete(f"/api/v1/admin/profiles/{a['id']}", headers=admin_headers)
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "PROFILE_IS_PARENT"

        client.patch(f"/api/v1/admin/profiles/{b['id']}",
                    json={"parent_role_id": None}, headers=admin_headers)
        r = client.delete(f"/api/v1/admin/profiles/{a['id']}", headers=admin_headers)
        assert r.status_code == 204

    def _employee_with_profile(self, client, admin_headers, profile_code, full_name):
        emp = client.post("/api/v1/admin/employees",
                          json={"email": f"hier.{uuid.uuid4().hex[:8]}@example.com",
                               "full_name": full_name},
                          headers=admin_headers).json()
        client.put(f"/api/v1/admin/employees/{emp['id']}/profiles",
                  json={"profile_codes": [profile_code]}, headers=admin_headers)
        headers = {"Authorization": f"Bearer {mint_token_for_profiles(emp['id'], {profile_code})}"}
        return emp["id"], headers

    def test_manager_sees_subordinates_row_but_not_a_sibling_holders(self, client, admin_headers):
        """Director sees the rep's lead purely via the hierarchy relationship
        (record_access_service.can_user_access_record()'s hierarchy path);
        Sibling (an unrelated profile, not an ancestor) does not."""
        director = _create_profile(client, admin_headers, display_name="Western Sales Director")
        rep = _create_profile(client, admin_headers, display_name="Western Sales Rep")
        sibling = _create_profile(client, admin_headers, display_name="Eastern Sales Rep")
        client.patch(f"/api/v1/admin/profiles/{rep['id']}",
                    json={"parent_role_id": director["id"]}, headers=admin_headers)
        for p in (director, rep, sibling):
            client.put(f"/api/v1/admin/profiles/{p['id']}/capabilities",
                      json={"capability_keys": ["leads.read", "leads.create"]}, headers=admin_headers)

        _, director_headers = self._employee_with_profile(client, admin_headers, director["code"], "Director")
        rep_id, rep_headers = self._employee_with_profile(client, admin_headers, rep["code"], "Rep")
        _, sibling_headers = self._employee_with_profile(client, admin_headers, sibling["code"], "Sibling")

        lead = client.post("/api/v1/leads", json={
            "company_name": "Hierarchy Co", "contact_email": "test.lead@example.com", "last_name": "Singh", "owner_employee_id": rep_id,
        }, headers=rep_headers)
        assert lead.status_code == 201, lead.text
        lead_id = lead.json()["id"]

        # Director sees the rep's lead — subordinate in the hierarchy.
        r = client.get(f"/api/v1/leads/{lead_id}", headers=director_headers)
        assert r.status_code == 200

        # Sibling (unrelated profile, not an ancestor) does not.
        r = client.get(f"/api/v1/leads/{lead_id}", headers=sibling_headers)
        assert r.status_code == 403

        # The rep still sees their own lead — ownership, not hierarchy.
        r = client.get(f"/api/v1/leads/{lead_id}", headers=rep_headers)
        assert r.status_code == 200  # owns it directly


class TestObjectCrudPermissions:
    """Lead/Account/Opportunity CRUD split into fine-grained capabilities —
    leads.create/edit/delete/read etc. — replacing the old bundled
    leads.write/platform.read for just these three objects' own core routes.
    See utils/permissions.py's docstring for what stays on the old keys
    (sub-resource/action routes)."""

    def test_read_without_create_can_list_but_not_create(self, client, admin_headers):
        profile = _create_profile(client, admin_headers)
        client.put(f"/api/v1/admin/profiles/{profile['id']}/capabilities",
                  json={"capability_keys": ["leads.read"]}, headers=admin_headers)
        emp = client.post("/api/v1/admin/employees",
                          json={"email": f"readonly.{uuid.uuid4().hex[:8]}@example.com",
                               "full_name": "Read Only Rep"},
                          headers=admin_headers).json()
        client.put(f"/api/v1/admin/employees/{emp['id']}/profiles",
                  json={"profile_codes": [profile["code"]]}, headers=admin_headers)
        headers = {"Authorization": f"Bearer {mint_token_for_profiles(emp['id'], {profile['code']})}"}

        assert client.get("/api/v1/leads", headers=headers).status_code == 200
        r = client.post("/api/v1/leads", json={"company_name": "X", "contact_email": "test.lead@example.com", "last_name": "Y"}, headers=headers)
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "FORBIDDEN"

    def test_create_without_edit_or_delete_cannot_edit_or_delete(self, client, admin_headers):
        profile = _create_profile(client, admin_headers)
        client.put(f"/api/v1/admin/profiles/{profile['id']}/capabilities",
                  json={"capability_keys": ["leads.read", "leads.create"]}, headers=admin_headers)
        emp = client.post("/api/v1/admin/employees",
                          json={"email": f"createonly.{uuid.uuid4().hex[:8]}@example.com",
                               "full_name": "Create Only Rep"},
                          headers=admin_headers).json()
        client.put(f"/api/v1/admin/employees/{emp['id']}/profiles",
                  json={"profile_codes": [profile["code"]]}, headers=admin_headers)
        headers = {"Authorization": f"Bearer {mint_token_for_profiles(emp['id'], {profile['code']})}"}

        lead = client.post("/api/v1/leads", json={
            "company_name": "X", "contact_email": "test.lead@example.com", "last_name": "Y", "owner_employee_id": emp["id"],
        }, headers=headers)
        assert lead.status_code == 201, lead.text

        r = client.patch(f"/api/v1/leads/{lead.json()['id']}", json={"industry": "Z"}, headers=headers)
        assert r.status_code == 403
        r = client.delete(f"/api/v1/leads/{lead.json()['id']}", headers=headers)
        assert r.status_code == 403

    def test_account_delete_defaults_to_admin_only(self, client, admin_headers, sales_headers):
        account = client.post("/api/v1/accounts", json={"legal_name": "Delete Test Co"},
                              headers=admin_headers).json()
        # SALES already holds accounts.create/accounts.edit (seeded from the
        # old accounts.write) but NOT the new accounts.delete.
        r = client.delete(f"/api/v1/accounts/{account['id']}", headers=sales_headers)
        assert r.status_code == 403
        r = client.delete(f"/api/v1/accounts/{account['id']}", headers=admin_headers)
        assert r.status_code == 204

    def test_leads_write_still_gates_sub_resource_actions(self, client, admin_headers):
        """A profile holding only the fine-grained keys (no legacy
        leads.write) can create/edit a lead but not reach the AI-drafting
        sub-resource actions still gated by leads.write."""
        profile = _create_profile(client, admin_headers)
        client.put(f"/api/v1/admin/profiles/{profile['id']}/capabilities",
                  json={"capability_keys": ["leads.read", "leads.create", "leads.edit"]},
                  headers=admin_headers)
        emp = client.post("/api/v1/admin/employees",
                          json={"email": f"finegrained.{uuid.uuid4().hex[:8]}@example.com",
                               "full_name": "Fine Grained Rep"},
                          headers=admin_headers).json()
        client.put(f"/api/v1/admin/employees/{emp['id']}/profiles",
                  json={"profile_codes": [profile["code"]]}, headers=admin_headers)
        headers = {"Authorization": f"Bearer {mint_token_for_profiles(emp['id'], {profile['code']})}"}

        lead = client.post("/api/v1/leads", json={
            "company_name": "X", "contact_email": "test.lead@example.com", "last_name": "Y", "owner_employee_id": emp["id"],
        }, headers=headers)
        assert lead.status_code == 201, lead.text
        r = client.patch(f"/api/v1/leads/{lead.json()['id']}", json={"industry": "Z"}, headers=headers)
        assert r.status_code == 200

        r = client.post(f"/api/v1/leads/{lead.json()['id']}/email-draft", headers=headers)
        assert r.status_code == 403  # still gated by leads.write, which this profile never held
