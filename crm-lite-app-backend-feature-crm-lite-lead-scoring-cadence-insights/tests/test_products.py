"""Product catalog (what we sell) — admin-configurable, global config that
crm_service.generate_email_draft()/generate_call_prep() match a researched
lead against (see test_ai_drafting.py for that half).

Persistent, shared Postgres DB with no per-test rollback — list() returns
every product ever created across every test run, so assertions check "the
product we just made is somewhere in the list" via a uuid4-suffixed name,
never an exact count.
"""
import uuid


def _product(client, headers, **overrides):
    payload = {"name": f"Test Product {uuid.uuid4()}", "description": "Does something useful."} | overrides
    r = client.post("/api/v1/products", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


class TestProductCRUD:
    def test_create_and_get(self, client, admin_headers):
        product = _product(client, admin_headers, target_industry="Healthcare")
        assert product["is_active"] is True
        assert product["target_industry"] == "Healthcare"

        r = client.get(f"/api/v1/products/{product['id']}", headers=admin_headers)
        assert r.status_code == 200, r.text
        assert r.json()["id"] == product["id"]

    def test_new_product_appears_in_list(self, client, admin_headers):
        product = _product(client, admin_headers)
        r = client.get("/api/v1/products", headers=admin_headers)
        assert r.status_code == 200, r.text
        assert any(p["id"] == product["id"] for p in r.json())

    def test_update(self, client, admin_headers):
        product = _product(client, admin_headers)
        r = client.patch(f"/api/v1/products/{product['id']}",
                         json={"description": "An updated description.", "is_active": False},
                         headers=admin_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["description"] == "An updated description."
        assert body["is_active"] is False

    def test_delete_removes_from_active_list(self, client, admin_headers):
        product = _product(client, admin_headers)
        r = client.delete(f"/api/v1/products/{product['id']}", headers=admin_headers)
        assert r.status_code == 204

        r = client.get("/api/v1/products", headers=admin_headers)
        assert not any(p["id"] == product["id"] for p in r.json())

    def test_get_missing_product_is_404(self, client, admin_headers):
        r = client.get(f"/api/v1/products/{uuid.uuid4()}", headers=admin_headers)
        assert r.status_code == 404


class TestProductWritePermission:
    """Global catalog config — admin-only, same tier as lead-scoring-rules
    and cadence-templates (see utils/permissions.py)."""

    def test_sales_cannot_create_product(self, client, sales_headers):
        r = client.post("/api/v1/products", json={"name": "Nope", "description": "Nope."},
                        headers=sales_headers)
        assert r.status_code == 403

    def test_sales_can_still_read_products(self, client, admin_headers, sales_headers):
        _product(client, admin_headers)
        r = client.get("/api/v1/products", headers=sales_headers)
        assert r.status_code == 200
