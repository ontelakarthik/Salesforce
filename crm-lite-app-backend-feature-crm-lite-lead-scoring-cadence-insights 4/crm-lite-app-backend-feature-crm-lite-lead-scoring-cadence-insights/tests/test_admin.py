"""Admin module (§1/§13.5) — employees, employee roles, teams, generic
lookup value management. Exercised against the real Postgres container.
"""
import uuid

import pytest

from src.services import admin_service
from src.utils.exceptions import DomainError


class TestEmployees:
    def test_create_list_update(self, client, admin_headers):
        r = client.post("/api/v1/admin/employees",
                        json={"email": f"carol.{uuid.uuid4().hex[:8]}@example.com", "full_name": "Carol"},
                        headers=admin_headers)
        assert r.status_code == 201
        emp = r.json()
        assert emp["is_active"] is True
        assert emp["roles"] == []

        r = client.get("/api/v1/admin/employees", headers=admin_headers)
        assert r.status_code == 200
        assert any(e["id"] == emp["id"] for e in r.json())

        r = client.patch(f"/api/v1/admin/employees/{emp['id']}", json={"is_active": False},
                         headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["is_active"] is False

    def test_non_admin_forbidden(self, client, sales_headers):
        r = client.get("/api/v1/admin/employees", headers=sales_headers)
        assert r.status_code == 403


class TestEmployeeDirectory:
    """GET /employees/directory — unlike /admin/employees, every role can
    call this; it exists so the UI can resolve an owner/signer/reviewer id
    to a display name anywhere in the app without needing the full,
    admin-only employee record."""

    def test_available_to_non_admin_roles(self, client, admin_headers, sales_headers):
        email = f"directory.{uuid.uuid4().hex[:8]}@example.com"
        emp = client.post("/api/v1/admin/employees", json={"email": email, "full_name": "Directory Case"},
                         headers=admin_headers).json()

        r = client.get("/api/v1/employees/directory", headers=sales_headers)
        assert r.status_code == 200, r.text
        entry = next(e for e in r.json() if e["id"] == emp["id"])
        assert entry == {"id": emp["id"], "full_name": "Directory Case"}
        # No email, roles, or is_active — deliberately minimal.
        assert set(entry.keys()) == {"id", "full_name"}

    def test_includes_deactivated_employees(self, client, admin_headers, sales_headers):
        email = f"deactivated.{uuid.uuid4().hex[:8]}@example.com"
        emp = client.post("/api/v1/admin/employees", json={"email": email, "full_name": "Deactivated Case"},
                         headers=admin_headers).json()
        client.patch(f"/api/v1/admin/employees/{emp['id']}", json={"is_active": False}, headers=admin_headers)

        r = client.get("/api/v1/employees/directory", headers=sales_headers)
        assert any(e["id"] == emp["id"] for e in r.json()), \
            "a deactivated employee must still resolve by name on historical records"


class TestEmployeeRoles:
    def test_set_roles_is_a_full_replace(self, client, admin_headers):
        emp = client.post("/api/v1/admin/employees",
                         json={"email": f"dave.{uuid.uuid4().hex[:8]}@example.com", "full_name": "Dave"},
                         headers=admin_headers).json()

        r = client.put(f"/api/v1/admin/employees/{emp['id']}/profiles",
                       json={"profile_codes": ["SALES", "ACCOUNT_EXEC"]}, headers=admin_headers)
        assert r.status_code == 200
        assert set(r.json()["roles"]) == {"SALES", "ACCOUNT_EXEC"}

        r = client.put(f"/api/v1/admin/employees/{emp['id']}/profiles",
                       json={"profile_codes": ["ADMIN"]}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["roles"] == ["ADMIN"]  # SALES/ACCOUNT_EXEC revoked, not accumulated

    def test_unknown_role_code_422s(self, client, admin_headers):
        emp = client.post("/api/v1/admin/employees",
                         json={"email": f"erin.{uuid.uuid4().hex[:8]}@example.com", "full_name": "Erin"},
                         headers=admin_headers).json()
        r = client.put(f"/api/v1/admin/employees/{emp['id']}/profiles",
                      json={"profile_codes": ["NOT_A_ROLE"]}, headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "ROLE_NOT_FOUND"


class TestTeams:
    def test_create_list_update(self, client, admin_headers):
        r = client.post("/api/v1/admin/teams",
                        json={"display_name": "Support DL", "address": "support@example.com"},
                        headers=admin_headers)
        assert r.status_code == 201
        team = r.json()

        r = client.get("/api/v1/admin/teams", headers=admin_headers)
        assert r.status_code == 200
        assert any(t["id"] == team["id"] for t in r.json())

        r = client.patch(f"/api/v1/admin/teams/{team['id']}", json={"is_active": False},
                         headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["is_active"] is False


class TestLookups:
    def test_add_update_lookup_value(self, client, admin_headers):
        code = f"TEST_{uuid.uuid4().hex[:6].upper()}"
        r = client.post("/api/v1/admin/lookups/contact_type",
                        json={"code": code, "display_name": "Test Contact Type"}, headers=admin_headers)
        assert r.status_code == 201
        row = r.json()
        assert row["code"] == code

        r = client.patch(f"/api/v1/admin/lookups/contact_type/{row['id']}",
                         json={"display_name": "Renamed"}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["display_name"] == "Renamed"

    def test_unknown_table_404s(self, client, admin_headers):
        r = client.get("/api/v1/admin/lookups/not_a_real_table", headers=admin_headers)
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "LOOKUP_TABLE_NOT_FOUND"

    def test_delete_in_use_lookup_value_is_blocked(self, client, admin_headers):
        # No DELETE /admin/lookups/{table}/{id} route is registered (the API
        # spec's 10 admin endpoints don't include one — see admin_routes.py),
        # but admin_service.delete_lookup exists for reuse and its
        # IntegrityError -> LOOKUP_IN_USE translation is real logic worth
        # covering directly. account_type=PROSPECT is referenced by every
        # freshly created account, so deleting it must fail, not 500.
        client.post("/api/v1/accounts", json={"legal_name": "Lookup Conflict Co"}, headers=admin_headers)
        rows = admin_service.list_lookups("account_type")
        prospect = next(row for row in rows if row.code == "PROSPECT")
        with pytest.raises(DomainError) as exc_info:
            admin_service.delete_lookup("account_type", prospect.id)
        assert exc_info.value.code == "LOOKUP_IN_USE"
        assert exc_info.value.status_code == 409
