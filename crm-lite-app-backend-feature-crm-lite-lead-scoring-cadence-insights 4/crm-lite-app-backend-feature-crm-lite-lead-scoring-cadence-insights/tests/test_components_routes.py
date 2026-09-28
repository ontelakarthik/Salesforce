"""Route registration + RBAC smoke tests (skeleton)."""


def test_all_165_endpoints_registered():
    """159 prior + 6 new Organization-Wide Default / Record Sharing / cadence-
    scheduler routes (GET/PUT /org-wide-defaults, GET/POST /record-shares,
    DELETE /record-shares/{id}, POST /cadence/advance-due-steps) — see
    crm_routes.py's OWD/Record Sharing/cadence scheduler sections."""
    from src.server import app
    spec = app.openapi()
    n = sum(len(ops) for p, ops in spec["paths"].items() if p.startswith("/api/v1"))
    assert n == 165, f"expected 165, found {n}"


def test_opportunities_endpoint_is_implemented(client):
    r = client.get("/api/v1/opportunities")   # DEV_AUTH_BYPASS -> ADMIN, sees all
    assert r.status_code == 200


def test_no_endpoint_is_still_a_stub(client):
    """Every module (account, crm, contracts, delivery, project, activity,
    platform, admin, auth) is now implemented — no route should still 501."""
    from src.server import app
    spec = app.openapi()
    param_free_gets = [
        path for path, ops in spec["paths"].items()
        if path.startswith("/api/v1") and "{" not in path and "get" in ops
    ]
    assert param_free_gets, "expected at least one parameter-free GET route"
    for path in param_free_gets:
        r = client.get(path)
        assert r.status_code != 501, f"{path} is still a stub"


def test_accounts_endpoint_is_implemented(client):
    r = client.get("/api/v1/accounts")   # DEV_AUTH_BYPASS -> ADMIN, sees all
    assert r.status_code == 200
    body = r.json()
    assert {"items", "total", "page", "page_size"} <= body.keys()


def test_rbac_forbids_sales_signing(client, sales_headers):
    r = client.post("/api/v1/agreements/x/sign", headers=sales_headers)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"
