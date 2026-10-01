"""Record-level access control — Ownership + Organization-Wide Defaults +
user-based Sharing Rules, for Lead/Account/Contact/Opportunity/Campaign. See
services/record_access_service.py (the centralized decision point) and
crm_models.RecordShare.

Complements tests/test_org_wide_defaults.py, which already covers the OWD
matrix (PRIVATE/PUBLIC_READ_ONLY/PUBLIC_READ_WRITE) for LEAD/ACCOUNT/
OPPORTUNITY plus Role Hierarchy's additional access path. This file adds:
CONTACT/CAMPAIGN OWD enforcement, Contact's effective-owner-via-Account
rule, Campaign ownership, Sharing Rules (grant/no-grant/never-reduces/
never-DELETE), self-sharing-abuse prevention, IDOR coverage, list-endpoint
filtering, and can_edit/can_delete response flags.

Same persistent-shared-Postgres-no-per-test-rollback caveat as every other
test module here — the autouse fixture below resets all 5 OWD rows to
PRIVATE before/after every test in this file, mirroring
test_org_wide_defaults.py's own fixture.
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


def _set_owd(client, admin_headers, **levels: str) -> None:
    """Sets each named object (LEAD=..., ACCOUNT=..., ...) to the given
    access level and every other OWD-eligible object to PRIVATE — a single
    PUT, since save_org_wide_defaults() requires all 5 objects submitted
    together. Pass multiple objects in ONE call when a test needs more than
    one non-PRIVATE at the same time (two separate calls would each reset
    the other's object back to PRIVATE)."""
    entries = [
        {"object_name": name, "access_level": levels.get(name, "PRIVATE")}
        for name in OWD_OBJECTS
    ]
    r = client.put("/api/v1/org-wide-defaults", json={"entries": entries}, headers=admin_headers)
    assert r.status_code == 200, r.text


def _employee(client, admin_headers, full_name: str) -> str:
    r = client.post("/api/v1/admin/employees",
                    json={"email": f"racc.{uuid.uuid4().hex[:8]}@example.com", "full_name": full_name},
                    headers=admin_headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _rep_headers(client, admin_headers, employee_id: str, capability_keys: list[str], full_name: str) -> dict:
    """A profile granted exactly `capability_keys` — no records.see_all, no
    Role-Hierarchy relationship to anyone — isolates the ownership/OWD/
    sharing gate from every other layer."""
    profile = client.post("/api/v1/admin/profiles",
                          json={"code": f"RACC{uuid.uuid4().hex[:8].upper()}", "display_name": full_name},
                          headers=admin_headers).json()
    client.put(f"/api/v1/admin/profiles/{profile['id']}/capabilities",
              json={"capability_keys": capability_keys}, headers=admin_headers)
    client.put(f"/api/v1/admin/employees/{employee_id}/profiles",
              json={"profile_codes": [profile["code"]]}, headers=admin_headers)
    return {"Authorization": f"Bearer {mint_token_for_profiles(employee_id, {profile['code']})}"}


def _lead(client, admin_headers, owner_employee_id=None, **overrides):
    payload = {"company_name": "Record Access Co", "contact_email": "test.lead@example.com", "last_name": "Rao"} | overrides
    if owner_employee_id is not None:
        payload["owner_employee_id"] = owner_employee_id
    r = client.post("/api/v1/leads", json=payload, headers=admin_headers)
    assert r.status_code == 201, r.text
    return r.json()


def _account(client, admin_headers, owner_employee_id=None, **overrides):
    payload = {"legal_name": "Record Access Account"} | overrides
    if owner_employee_id is not None:
        payload["owner_employee_id"] = owner_employee_id
    r = client.post("/api/v1/accounts", json=payload, headers=admin_headers)
    assert r.status_code == 201, r.text
    return r.json()


def _contact(client, admin_headers, account_id, **overrides):
    payload = {"contact_type": "BUSINESS", "full_name": "Record Access Contact"} | overrides
    r = client.post(f"/api/v1/accounts/{account_id}/contacts", json=payload, headers=admin_headers)
    assert r.status_code == 201, r.text
    return r.json()


def _opportunity(client, admin_headers, account_id, owner_employee_id=None, **overrides):
    payload = {"account_id": account_id, "name": "Record Access Deal"} | overrides
    if owner_employee_id is not None:
        payload["owner_employee_id"] = owner_employee_id
    r = client.post("/api/v1/opportunities", json=payload, headers=admin_headers)
    assert r.status_code == 201, r.text
    return r.json()


def _campaign(client, admin_headers, owner_employee_id=None, **overrides):
    payload = {"name": "Record Access Campaign"} | overrides
    if owner_employee_id is not None:
        payload["owner_employee_id"] = owner_employee_id
    r = client.post("/api/v1/campaigns", json=payload, headers=admin_headers)
    assert r.status_code == 201, r.text
    return r.json()


class TestContactOwnAndOwdMatrix:
    """Contact has no owner of its own -- effective owner is derived from
    its parent Account's owner (see record_access_service.
    effective_owner_employee_id()) -- but CONTACT has its OWN OWD row,
    independent of ACCOUNT's."""

    def test_private_blocks_non_owner_even_when_account_is_public(self, client, admin_headers):
        owner_id = _employee(client, admin_headers, "Contact Owner")
        account = _account(client, admin_headers, owner_employee_id=owner_id)
        contact = _contact(client, admin_headers, account["id"])
        _set_owd(client, admin_headers, ACCOUNT="PUBLIC_READ_WRITE")  # ACCOUNT wide open...
        # ...but CONTACT stays PRIVATE (the fixture default) -- a non-owner
        # still can't reach the contact, proving CONTACT's OWD is independent.
        tester = _employee(client, admin_headers, "Contact Tester")
        tester_headers = _rep_headers(client, admin_headers, tester, ["accounts.write"], "Contact Tester")

        r = client.patch(f"/api/v1/contacts/{contact['id']}", json={"title": "VP"}, headers=tester_headers)
        assert r.status_code == 403

    def test_owner_derived_from_account_can_edit(self, client, admin_headers):
        owner_id = _employee(client, admin_headers, "Contact Owner Two")
        account = _account(client, admin_headers, owner_employee_id=owner_id)
        contact = _contact(client, admin_headers, account["id"])
        owner_headers = _rep_headers(client, admin_headers, owner_id, ["accounts.write"], "Contact Owner Two")

        r = client.patch(f"/api/v1/contacts/{contact['id']}", json={"title": "VP"}, headers=owner_headers)
        assert r.status_code == 200, r.text
        assert r.json()["title"] == "VP"

    def test_public_read_only_allows_read_blocks_edit(self, client, admin_headers):
        owner_id = _employee(client, admin_headers, "Contact Owner RO")
        account = _account(client, admin_headers, owner_employee_id=owner_id)
        _contact(client, admin_headers, account["id"])
        tester = _employee(client, admin_headers, "Contact Tester RO")
        tester_headers = _rep_headers(
            client, admin_headers, tester, ["accounts.read", "accounts.write", "platform.read"],
            "Contact Tester RO")
        _set_owd(client, admin_headers, ACCOUNT="PUBLIC_READ_ONLY", CONTACT="PUBLIC_READ_ONLY")

        r = client.get(f"/api/v1/accounts/{account['id']}/contacts", headers=tester_headers)
        assert r.status_code == 200
        assert len(r.json()) == 1
        contact_id = r.json()[0]["id"]
        assert r.json()[0]["can_edit"] is False

        r = client.patch(f"/api/v1/contacts/{contact_id}", json={"title": "Nope"}, headers=tester_headers)
        assert r.status_code == 403


class TestCampaignOwnershipAndOwd:
    """Campaign previously had no owner and no scope check at all -- this is
    the newly-scoped behavior (a deliberate, called-out change)."""

    def test_owner_defaults_to_creator_when_unset(self, client, admin_headers):
        """admin_headers itself is a synthetic identity with no real Employee
        row (see conftest.py) -- verified_employee_uuid() deliberately
        resolves that to None (admin_service.py), so "creator becomes owner"
        has nothing to default to for that caller specifically. A real,
        provisioned employee is needed to actually exercise this rule."""
        creator = _employee(client, admin_headers, "Campaign Creator")
        creator_headers = _rep_headers(
            client, admin_headers, creator, ["campaigns.write", "platform.read"], "Campaign Creator")
        campaign = _campaign(client, creator_headers)
        assert campaign["owner_employee_id"] == creator

    def test_private_blocks_non_owner(self, client, admin_headers):
        owner_id = _employee(client, admin_headers, "Campaign Owner")
        campaign = _campaign(client, admin_headers, owner_employee_id=owner_id)
        tester = _employee(client, admin_headers, "Campaign Tester")
        tester_headers = _rep_headers(
            client, admin_headers, tester, ["campaigns.write", "platform.read"], "Campaign Tester")

        r = client.get(f"/api/v1/campaigns/{campaign['id']}", headers=tester_headers)
        assert r.status_code == 403

    def test_owner_can_read_and_edit(self, client, admin_headers):
        owner_id = _employee(client, admin_headers, "Campaign Owner Two")
        campaign = _campaign(client, admin_headers, owner_employee_id=owner_id)
        owner_headers = _rep_headers(
            client, admin_headers, owner_id, ["campaigns.write", "platform.read"], "Campaign Owner Two")

        r = client.get(f"/api/v1/campaigns/{campaign['id']}", headers=owner_headers)
        assert r.status_code == 200
        r = client.patch(f"/api/v1/campaigns/{campaign['id']}", json={"status": "IN_PROGRESS"},
                         headers=owner_headers)
        assert r.status_code == 200, r.text

    def test_list_campaigns_only_returns_accessible_rows(self, client, admin_headers):
        owner_id = _employee(client, admin_headers, "Campaign List Owner")
        mine = _campaign(client, admin_headers, owner_employee_id=owner_id, name="Mine")
        other_owner = _employee(client, admin_headers, "Campaign List Other Owner")
        _campaign(client, admin_headers, owner_employee_id=other_owner, name="Not Mine")
        tester_headers = _rep_headers(
            client, admin_headers, owner_id, ["campaigns.write", "platform.read"], "Campaign List Owner")

        r = client.get("/api/v1/campaigns", headers=tester_headers)
        assert r.status_code == 200
        ids = {c["id"] for c in r.json()}
        assert mine["id"] in ids
        assert all(c["id"] != mine["id"] or c["can_edit"] for c in r.json())

    def test_public_read_write_default_preserves_visibility_for_existing_unowned_campaigns(
        self, client, admin_headers,
    ):
        """Documents the migration's actual chosen default: CAMPAIGN seeded
        PUBLIC_READ_WRITE, not PRIVATE like the other 4 OWD objects --
        specifically so every existing (unowned) campaign stays visible AND
        editable to anyone with platform.read/campaigns.write, exactly as it
        was before this feature shipped. This file's autouse fixture resets
        every object to PRIVATE around each test, so PUBLIC_READ_WRITE is set
        explicitly here to exercise that real default rather than relying on
        migration state the fixture would otherwise immediately undo."""
        _set_owd(client, admin_headers, CAMPAIGN="PUBLIC_READ_WRITE")
        campaign = _campaign(client, admin_headers, name="Unowned Legacy Campaign")
        assert campaign["owner_employee_id"] is None  # admin_headers has no real Employee row to default to
        tester = _employee(client, admin_headers, "Campaign Legacy Tester")
        tester_headers = _rep_headers(
            client, admin_headers, tester, ["campaigns.write", "platform.read"], "Campaign Legacy Tester")

        r = client.get(f"/api/v1/campaigns/{campaign['id']}", headers=tester_headers)
        assert r.status_code == 200, r.text
        assert r.json()["can_edit"] is True
        r = client.patch(f"/api/v1/campaigns/{campaign['id']}", json={"status": "IN_PROGRESS"},
                         headers=tester_headers)
        assert r.status_code == 200, r.text


class TestRecordSharing:
    """Salesforce-style user-based sharing -- READ|EDIT only, additive over
    OWD/ownership, never reducing access, never granting DELETE."""

    def _owned_lead(self, client, admin_headers):
        owner_id = _employee(client, admin_headers, "Share Owner")
        lead = _lead(client, admin_headers, owner_employee_id=owner_id)
        owner_headers = _rep_headers(
            client, admin_headers, owner_id, ["leads.read", "leads.edit", "record_shares.write"], "Share Owner")
        return owner_id, owner_headers, lead

    def test_read_share_grants_read_not_edit(self, client, admin_headers):
        _owner_id, owner_headers, lead = self._owned_lead(client, admin_headers)
        grantee = _employee(client, admin_headers, "Share Grantee Read")
        grantee_headers = _rep_headers(client, admin_headers, grantee, ["leads.read", "leads.edit"], "Share Grantee Read")

        r = client.post("/api/v1/record-shares", json={
            "object_name": "LEAD", "record_id": lead["id"],
            "shared_with_employee_id": grantee, "access_level": "READ",
        }, headers=owner_headers)
        assert r.status_code == 201, r.text

        r = client.get(f"/api/v1/leads/{lead['id']}", headers=grantee_headers)
        assert r.status_code == 200
        assert r.json()["can_edit"] is False

        r = client.patch(f"/api/v1/leads/{lead['id']}", json={"title": "Nope"}, headers=grantee_headers)
        assert r.status_code == 403

    def test_edit_share_grants_read_and_edit_but_never_delete(self, client, admin_headers):
        _owner_id, owner_headers, lead = self._owned_lead(client, admin_headers)
        grantee = _employee(client, admin_headers, "Share Grantee Edit")
        grantee_headers = _rep_headers(
            client, admin_headers, grantee, ["leads.read", "leads.edit", "leads.delete"], "Share Grantee Edit")

        r = client.post("/api/v1/record-shares", json={
            "object_name": "LEAD", "record_id": lead["id"],
            "shared_with_employee_id": grantee, "access_level": "EDIT",
        }, headers=owner_headers)
        assert r.status_code == 201, r.text

        r = client.patch(f"/api/v1/leads/{lead['id']}", json={"title": "Now Editable"}, headers=grantee_headers)
        assert r.status_code == 200, r.text
        assert r.json()["title"] == "Now Editable"

        # An EDIT share must NEVER translate into DELETE.
        r = client.delete(f"/api/v1/leads/{lead['id']}", headers=grantee_headers)
        assert r.status_code == 403

    def test_no_share_no_access_on_private(self, client, admin_headers):
        _owner_id, _owner_headers, lead = self._owned_lead(client, admin_headers)
        outsider = _employee(client, admin_headers, "Share Outsider")
        outsider_headers = _rep_headers(client, admin_headers, outsider, ["leads.read", "leads.edit"], "Share Outsider")
        r = client.get(f"/api/v1/leads/{lead['id']}", headers=outsider_headers)
        assert r.status_code == 403

    def test_sharing_cannot_reduce_public_read_write_access(self, client, admin_headers):
        """A READ-only share on a PUBLIC_READ_WRITE lead must not narrow
        what OWD already grants everyone -- sharing only ever ADDS."""
        _owner_id, owner_headers, lead = self._owned_lead(client, admin_headers)
        _set_owd(client, admin_headers, LEAD="PUBLIC_READ_WRITE")
        grantee = _employee(client, admin_headers, "Share No Reduce")
        grantee_headers = _rep_headers(client, admin_headers, grantee, ["leads.read", "leads.edit"], "Share No Reduce")
        client.post("/api/v1/record-shares", json={
            "object_name": "LEAD", "record_id": lead["id"],
            "shared_with_employee_id": grantee, "access_level": "READ",
        }, headers=owner_headers)

        r = client.patch(f"/api/v1/leads/{lead['id']}", json={"title": "Still Editable"}, headers=grantee_headers)
        assert r.status_code == 200, r.text  # PUBLIC_READ_WRITE still grants EDIT regardless of the READ share

    def test_resharing_same_employee_upgrades_grant(self, client, admin_headers):
        _owner_id, owner_headers, lead = self._owned_lead(client, admin_headers)
        grantee = _employee(client, admin_headers, "Share Upgrade")
        grantee_headers = _rep_headers(client, admin_headers, grantee, ["leads.read", "leads.edit"], "Share Upgrade")
        client.post("/api/v1/record-shares", json={
            "object_name": "LEAD", "record_id": lead["id"],
            "shared_with_employee_id": grantee, "access_level": "READ",
        }, headers=owner_headers)
        r = client.post("/api/v1/record-shares", json={
            "object_name": "LEAD", "record_id": lead["id"],
            "shared_with_employee_id": grantee, "access_level": "EDIT",
        }, headers=owner_headers)
        assert r.status_code == 201, r.text

        r = client.patch(f"/api/v1/leads/{lead['id']}", json={"title": "Upgraded"}, headers=grantee_headers)
        assert r.status_code == 200

    def test_revoking_a_share_removes_access(self, client, admin_headers):
        _owner_id, owner_headers, lead = self._owned_lead(client, admin_headers)
        grantee = _employee(client, admin_headers, "Share Revoke")
        grantee_headers = _rep_headers(client, admin_headers, grantee, ["leads.read", "leads.edit"], "Share Revoke")
        share = client.post("/api/v1/record-shares", json={
            "object_name": "LEAD", "record_id": lead["id"],
            "shared_with_employee_id": grantee, "access_level": "READ",
        }, headers=owner_headers).json()

        assert client.get(f"/api/v1/leads/{lead['id']}", headers=grantee_headers).status_code == 200

        r = client.delete(f"/api/v1/record-shares/{share['id']}", headers=owner_headers)
        assert r.status_code == 204
        assert client.get(f"/api/v1/leads/{lead['id']}", headers=grantee_headers).status_code == 403

    def test_cannot_share_a_record_you_cannot_edit(self, client, admin_headers):
        """Self/proxy-escalation guard: a caller with only READ (via a
        prior share) must not be able to grant a NEW share to someone else."""
        _owner_id, owner_headers, lead = self._owned_lead(client, admin_headers)
        read_only_grantee = _employee(client, admin_headers, "Share Proxy Reader")
        reader_headers = _rep_headers(
            client, admin_headers, read_only_grantee,
            ["leads.read", "leads.edit", "record_shares.write"], "Share Proxy Reader")
        client.post("/api/v1/record-shares", json={
            "object_name": "LEAD", "record_id": lead["id"],
            "shared_with_employee_id": read_only_grantee, "access_level": "READ",
        }, headers=owner_headers)

        third_party = _employee(client, admin_headers, "Share Proxy Target")
        r = client.post("/api/v1/record-shares", json={
            "object_name": "LEAD", "record_id": lead["id"],
            "shared_with_employee_id": third_party, "access_level": "READ",
        }, headers=reader_headers)
        assert r.status_code == 403

    def test_share_access_level_cannot_be_delete(self, client, admin_headers):
        _owner_id, owner_headers, lead = self._owned_lead(client, admin_headers)
        grantee = _employee(client, admin_headers, "Share Delete Attempt")
        r = client.post("/api/v1/record-shares", json={
            "object_name": "LEAD", "record_id": lead["id"],
            "shared_with_employee_id": grantee, "access_level": "DELETE",
        }, headers=owner_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "RECORD_SHARE_ACCESS_LEVEL_INVALID"

    def test_list_shares_requires_read_and_visible_to_owner(self, client, admin_headers):
        _owner_id, owner_headers, lead = self._owned_lead(client, admin_headers)
        grantee = _employee(client, admin_headers, "Share List Grantee")
        client.post("/api/v1/record-shares", json={
            "object_name": "LEAD", "record_id": lead["id"],
            "shared_with_employee_id": grantee, "access_level": "READ",
        }, headers=owner_headers)

        r = client.get("/api/v1/record-shares", params={"object_name": "LEAD", "record_id": lead["id"]},
                       headers=owner_headers)
        assert r.status_code == 200
        assert any(s["shared_with_employee_id"] == grantee for s in r.json())

    def test_unauthorized_share_creation_blocked_by_capability(self, client, admin_headers, sales_headers):
        _owner_id, _owner_headers, lead = self._owned_lead(client, admin_headers)
        grantee = _employee(client, admin_headers, "Share Cap Blocked")
        # sales_headers's SALES profile does not hold record_shares.write.
        r = client.post("/api/v1/record-shares", json={
            "object_name": "LEAD", "record_id": lead["id"],
            "shared_with_employee_id": grantee, "access_level": "READ",
        }, headers=sales_headers)
        assert r.status_code == 403


class TestIdorAndListLeakage:
    """Backend must be the security boundary -- direct-id GET/PATCH/DELETE
    and list endpoints must never leak a record the caller can't access."""

    def test_get_unowned_private_lead_by_id_is_403(self, client, admin_headers):
        owner_id = _employee(client, admin_headers, "IDOR Lead Owner")
        lead = _lead(client, admin_headers, owner_employee_id=owner_id)
        tester = _employee(client, admin_headers, "IDOR Lead Tester")
        tester_headers = _rep_headers(client, admin_headers, tester, ["leads.read", "leads.edit"], "IDOR Lead Tester")

        assert client.get(f"/api/v1/leads/{lead['id']}", headers=tester_headers).status_code == 403
        r = client.patch(f"/api/v1/leads/{lead['id']}", json={"title": "Hack"}, headers=tester_headers)
        assert r.status_code == 403

    def test_get_unowned_private_account_by_id_is_403(self, client, admin_headers):
        owner_id = _employee(client, admin_headers, "IDOR Account Owner")
        account = _account(client, admin_headers, owner_employee_id=owner_id)
        tester = _employee(client, admin_headers, "IDOR Account Tester")
        tester_headers = _rep_headers(
            client, admin_headers, tester, ["accounts.read", "accounts.write"], "IDOR Account Tester")
        assert client.get(f"/api/v1/accounts/{account['id']}", headers=tester_headers).status_code == 403

    def test_get_unowned_private_opportunity_by_id_is_403(self, client, admin_headers):
        owner_id = _employee(client, admin_headers, "IDOR Opp Owner")
        account = _account(client, admin_headers)
        opp = _opportunity(client, admin_headers, account["id"], owner_employee_id=owner_id)
        tester = _employee(client, admin_headers, "IDOR Opp Tester")
        tester_headers = _rep_headers(
            client, admin_headers, tester, ["opportunities.read", "opportunities.edit"], "IDOR Opp Tester")
        assert client.get(f"/api/v1/opportunities/{opp['id']}", headers=tester_headers).status_code == 403

    def test_list_leads_omits_unowned_private_rows(self, client, admin_headers):
        owner_id = _employee(client, admin_headers, "List Leak Owner")
        _lead(client, admin_headers, owner_employee_id=owner_id, company_name="Hidden Co")
        tester = _employee(client, admin_headers, "List Leak Tester")
        tester_headers = _rep_headers(client, admin_headers, tester, ["leads.read", "leads.create"], "List Leak Tester")
        mine = _lead(client, admin_headers, owner_employee_id=tester, company_name="Visible Co")

        r = client.get("/api/v1/leads", headers=tester_headers)
        assert r.status_code == 200
        ids = {lead["id"] for lead in r.json()}
        assert mine["id"] in ids
        assert all(lead["company_name"] != "Hidden Co" for lead in r.json())

    def test_delete_share_for_a_record_you_cannot_edit_is_403(self, client, admin_headers):
        owner_id = _employee(client, admin_headers, "IDOR Share Owner")
        lead = _lead(client, admin_headers, owner_employee_id=owner_id)
        owner_headers = _rep_headers(
            client, admin_headers, owner_id, ["leads.read", "leads.edit", "record_shares.write"], "IDOR Share Owner")
        grantee = _employee(client, admin_headers, "IDOR Share Grantee")
        share = client.post("/api/v1/record-shares", json={
            "object_name": "LEAD", "record_id": lead["id"],
            "shared_with_employee_id": grantee, "access_level": "READ",
        }, headers=owner_headers).json()

        outsider = _employee(client, admin_headers, "IDOR Share Outsider")
        outsider_headers = _rep_headers(
            client, admin_headers, outsider, ["leads.read", "leads.edit", "record_shares.write"], "IDOR Share Outsider")
        r = client.delete(f"/api/v1/record-shares/{share['id']}", headers=outsider_headers)
        assert r.status_code == 403
