"""Field-Level Security — admin-configurable per-(role, object, field)
visibility/editability, layered on top of (never replacing) the existing
object-level CAPABILITIES matrix and row-level ownership scoping. See
crm_service.py's "Field-Level Security" section and permissions.py's
field_permissions.write docstring.

This is a persistent, shared Postgres DB with no per-test rollback — every
test below uses its own field_name/object_name combination the OTHERS don't
touch (a full PUT /field-permissions replaces the ENTIRE set for one
object_name, so two tests sharing an object_name would clobber each other).
"""
import uuid

from src.repositories.admin_repository import get_profile_repository
from src.services.auth_service import mint_token_for_profiles


def _role_id(code: str) -> int:
    row = next(r for r in get_profile_repository().list() if r.code == code)
    return row.id


def _multi_role_headers(employee_id: str, profile_codes: set) -> dict:
    return {"Authorization": f"Bearer {mint_token_for_profiles(employee_id, profile_codes)}"}


def _lead(client, headers, **overrides):
    payload = {"company_name": "Meridian Health", "contact_email": "test.lead@example.com", "first_name": "Ananya", "last_name": "Rao"} | overrides
    r = client.post("/api/v1/leads", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _real_sales_rep(client, admin_headers) -> tuple[str, dict]:
    """owner_employee_id must FK a real `employee` row (see
    crm_service._validate_owner()) — the fixed SALES_ID test identity from
    conftest never has one, so redaction tests that need an actual owned
    lead provision a real employee and mint a token for their real id
    instead, same as test_crm.py's *_creator_becomes_owner_* tests."""
    email = f"flstest.{uuid.uuid4().hex[:8]}@example.com"
    emp = client.post("/api/v1/admin/employees", json={"email": email, "full_name": "FLS Test Rep"},
                      headers=admin_headers).json()
    return emp["id"], {"Authorization": f"Bearer {mint_token_for_profiles(emp['id'], {'SALES'})}"}


class TestFieldPermissionsAdminCrud:
    def test_leadership_and_sales_cannot_write(self, client, leadership_headers, sales_headers):
        payload = {"object_name": "LEAD", "entries": []}
        r = client.put("/api/v1/field-permissions", json=payload, headers=leadership_headers)
        assert r.status_code == 403
        r = client.put("/api/v1/field-permissions", json=payload, headers=sales_headers)
        assert r.status_code == 403

    def test_save_and_list_round_trips(self, client, admin_headers):
        role_id = _role_id("SALES")
        payload = {
            "object_name": "LEAD",
            "entries": [{"role_id": role_id, "object_name": "LEAD", "field_name": "industry",
                        "visible": True, "editable": False}],
        }
        r = client.put("/api/v1/field-permissions", json=payload, headers=admin_headers)
        assert r.status_code == 200, r.text
        assert len(r.json()) == 1
        assert r.json()[0]["editable"] is False

        r = client.get("/api/v1/field-permissions?object_name=LEAD", headers=admin_headers)
        assert r.status_code == 200
        assert [e["field_name"] for e in r.json()] == ["industry"]

    def test_save_replaces_the_full_set_for_that_object(self, client, admin_headers):
        role_id = _role_id("ACCOUNT_EXEC")
        first = {"object_name": "LEAD", "entries": [
            {"role_id": role_id, "object_name": "LEAD", "field_name": "website", "visible": False, "editable": False},
        ]}
        client.put("/api/v1/field-permissions", json=first, headers=admin_headers)
        second = {"object_name": "LEAD", "entries": [
            {"role_id": role_id, "object_name": "LEAD", "field_name": "linkedin_url",
             "visible": False, "editable": False},
        ]}
        r = client.put("/api/v1/field-permissions", json=second, headers=admin_headers)
        assert r.status_code == 200
        fields = {e["field_name"] for e in r.json()}
        assert fields == {"linkedin_url"}  # "website" from the first save is gone

    def test_rejects_unknown_field_name(self, client, admin_headers):
        payload = {"object_name": "LEAD", "entries": [
            {"role_id": _role_id("SALES"), "object_name": "LEAD", "field_name": "not_a_real_field",
             "visible": True, "editable": True},
        ]}
        r = client.put("/api/v1/field-permissions", json=payload, headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "FLS_FIELD_NOT_ELIGIBLE"

    def test_rejects_structural_field_not_in_eligible_set(self, client, admin_headers):
        payload = {"object_name": "LEAD", "entries": [
            {"role_id": _role_id("SALES"), "object_name": "LEAD", "field_name": "status",
             "visible": False, "editable": False},
        ]}
        r = client.put("/api/v1/field-permissions", json=payload, headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "FLS_FIELD_NOT_ELIGIBLE"

    def test_rejects_editable_without_visible(self, client, admin_headers):
        payload = {"object_name": "LEAD", "entries": [
            {"role_id": _role_id("SALES"), "object_name": "LEAD", "field_name": "industry",
             "visible": False, "editable": True},
        ]}
        r = client.put("/api/v1/field-permissions", json=payload, headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "FLS_EDITABLE_REQUIRES_VISIBLE"

    def test_rejects_admin_role(self, client, admin_headers):
        payload = {"object_name": "LEAD", "entries": [
            {"role_id": _role_id("ADMIN"), "object_name": "LEAD", "field_name": "industry",
             "visible": False, "editable": False},
        ]}
        r = client.put("/api/v1/field-permissions", json=payload, headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "FLS_CANNOT_RESTRICT_ADMIN"

    def test_unknown_object_name_404_on_list(self, client, admin_headers):
        r = client.get("/api/v1/field-permissions?object_name=NOT_AN_OBJECT", headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "FLS_OBJECT_UNKNOWN"


class TestEffectiveFieldPermissions:
    def test_no_rows_is_fully_permissive(self, client, sales_headers):
        r = client.get("/api/v1/field-permissions/effective?object_name=OPPORTUNITY", headers=sales_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["estimated_value"] == {"visible": True, "editable": True}

    def test_admin_is_always_fully_permissive_even_with_rows(self, client, admin_headers):
        client.put("/api/v1/field-permissions", json={
            "object_name": "ACCOUNT", "entries": [
                {"role_id": _role_id("SALES"), "object_name": "ACCOUNT", "field_name": "annual_revenue",
                 "visible": False, "editable": False},
            ]}, headers=admin_headers)
        r = client.get("/api/v1/field-permissions/effective?object_name=ACCOUNT", headers=admin_headers)
        assert r.json()["annual_revenue"] == {"visible": True, "editable": True}

    def test_one_unrestricted_held_role_keeps_field_visible(self, client, admin_headers):
        # SALES is restricted on Lead.rating, but the employee also holds
        # ACCOUNT_EXEC, which has no row at all -> union/most-permissive-wins
        # means the field must still be fully visible for them.
        client.put("/api/v1/field-permissions", json={
            "object_name": "LEAD", "entries": [
                {"role_id": _role_id("SALES"), "object_name": "LEAD", "field_name": "rating",
                 "visible": False, "editable": False},
            ]}, headers=admin_headers)
        dual_headers = _multi_role_headers(str(uuid.uuid4()), {"SALES", "ACCOUNT_EXEC"})
        r = client.get("/api/v1/field-permissions/effective?object_name=LEAD", headers=dual_headers)
        assert r.json()["rating"] == {"visible": True, "editable": True}

    def test_restricted_on_every_held_role_narrows(self, client, admin_headers):
        client.put("/api/v1/field-permissions", json={
            "object_name": "LEAD", "entries": [
                {"role_id": _role_id("SALES"), "object_name": "LEAD", "field_name": "source",
                 "visible": False, "editable": False},
                {"role_id": _role_id("ACCOUNT_EXEC"), "object_name": "LEAD", "field_name": "source",
                 "visible": False, "editable": False},
            ]}, headers=admin_headers)
        dual_headers = _multi_role_headers(str(uuid.uuid4()), {"SALES", "ACCOUNT_EXEC"})
        r = client.get("/api/v1/field-permissions/effective?object_name=LEAD", headers=dual_headers)
        assert r.json()["source"] == {"visible": False, "editable": False}


class TestRedactionEndToEnd:
    def test_restricted_field_is_null_for_sales_but_real_for_admin(self, client, admin_headers):
        client.put("/api/v1/field-permissions", json={
            "object_name": "LEAD", "entries": [
                {"role_id": _role_id("SALES"), "object_name": "LEAD", "field_name": "annual_revenue",
                 "visible": False, "editable": False},
            ]}, headers=admin_headers)
        # SALES only sees a lead it owns — make them the owner up front so
        # the scope check passes and FLS redaction is the only thing under
        # test.
        rep_id, rep_headers = _real_sales_rep(client, admin_headers)
        lead = _lead(client, admin_headers, annual_revenue=500000, owner_employee_id=rep_id)

        r = client.get(f"/api/v1/leads/{lead['id']}", headers=admin_headers)
        assert r.json()["annual_revenue"] == 500000

        r = client.get(f"/api/v1/leads/{lead['id']}", headers=rep_headers)
        assert r.status_code == 200, r.text
        assert r.json()["annual_revenue"] is None

    def test_restricted_field_dropped_silently_from_write_not_rejected(self, client, admin_headers):
        client.put("/api/v1/field-permissions", json={
            "object_name": "LEAD", "entries": [
                {"role_id": _role_id("SALES"), "object_name": "LEAD", "field_name": "industry",
                 "visible": True, "editable": False},
            ]}, headers=admin_headers)
        rep_id, rep_headers = _real_sales_rep(client, admin_headers)
        lead = _lead(client, admin_headers, owner_employee_id=rep_id, industry="Original")

        r = client.patch(f"/api/v1/leads/{lead['id']}",
                         json={"industry": "Attempted change", "title": "New title"}, headers=rep_headers)
        assert r.status_code == 200, r.text
        assert r.json()["title"] == "New title"  # unrestricted field still applied
        assert r.json()["industry"] == "Original"  # restricted field silently ignored, not an error

    def test_list_leads_redacts_every_row(self, client, admin_headers):
        client.put("/api/v1/field-permissions", json={
            "object_name": "LEAD", "entries": [
                {"role_id": _role_id("SALES"), "object_name": "LEAD", "field_name": "contact_email",
                 "visible": False, "editable": False},
            ]}, headers=admin_headers)
        rep_id, rep_headers = _real_sales_rep(client, admin_headers)
        _lead(client, admin_headers, owner_employee_id=rep_id,
             contact_email=f"redact-list.{uuid.uuid4().hex[:8]}@example.com")

        r = client.get("/api/v1/leads", headers=rep_headers)
        assert r.status_code == 200
        assert len(r.json()) >= 1
        assert all(row["contact_email"] is None for row in r.json())

    def test_restricted_field_dropped_silently_on_create_not_stored(self, client, admin_headers):
        """FLS applies to create_lead too, not just get/update/list — a
        field the caller can't edit is silently dropped from the create
        payload rather than stored as-is."""
        client.put("/api/v1/field-permissions", json={
            "object_name": "LEAD", "entries": [
                {"role_id": _role_id("SALES"), "object_name": "LEAD", "field_name": "annual_revenue",
                 "visible": False, "editable": False},
            ]}, headers=admin_headers)
        _, rep_headers = _real_sales_rep(client, admin_headers)

        r = client.post("/api/v1/leads", json={
            "company_name": "Create FLS Co", "contact_email": "test.lead@example.com", "last_name": "Rao", "annual_revenue": 999000,
        }, headers=rep_headers)
        assert r.status_code == 201, r.text
        assert r.json()["annual_revenue"] is None  # dropped on write, also redacted on the response

        # An admin (unrestricted) sees the true stored value — confirms the
        # value was never actually persisted, not merely redacted in this
        # one response.
        r2 = client.get(f"/api/v1/leads/{r.json()['id']}", headers=admin_headers)
        assert r2.json()["annual_revenue"] is None
