import os
import uuid

import pytest
from fastapi.testclient import TestClient

# config.py's DEV_AUTH_BYPASS now defaults to False (secure by default — see
# src/config/config.py) so a deployment can't silently grant ADMIN just by
# forgetting to configure it. Several tests below deliberately omit a bearer
# token to exercise "no token at all" behavior (see test_auth.py's
# TestCurrentEmployee and test_components_routes.py) — the same convenience
# DEV_AUTH_BYPASS=True is meant for in local dev, opted into here explicitly
# for the test session. Both this and JWT_SECRET must be set before
# src.config.config_reader's cached Settings singleton is first constructed,
# i.e. before importing src.server.
os.environ.setdefault("DEV_AUTH_BYPASS", "true")
os.environ.setdefault("JWT_SECRET", "test-only-secret-not-for-any-real-deployment")

from src.server import app  # noqa: E402
from src.services.auth_service import mint_token_for_profiles  # noqa: E402
from src.services.email_client import get_optional_email_sender  # noqa: E402


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def sent_emails():
    """Populated by _capture_email_sends below whenever a test (directly or
    via a flow like admin_service.create_employee()'s welcome email) sends
    mail — inspect this instead of hitting the real SMTP relay .env happens
    to have configured for manual testing."""
    return []


@pytest.fixture(autouse=True)
def _capture_email_sends(sent_emails):
    """create_employee() sends a real welcome email on every call — without
    this, every test that provisions an employee (there are many) would hit
    the real SMTP relay in .env. Individual tests that need to simulate "not
    configured" or "send failed" can still override get_optional_email_sender
    themselves after this fixture runs; this is just the default."""
    class _CapturingSender:
        def send(self, to_address: str, subject: str, body: str) -> None:
            sent_emails.append({"to": to_address, "subject": subject, "body": body})

    app.dependency_overrides[get_optional_email_sender] = lambda: _CapturingSender()
    yield
    app.dependency_overrides.pop(get_optional_email_sender, None)


# Deterministic, human-readable synthetic identities for RBAC tests, minted
# as real signed bearer tokens (the backend verifies these itself now — see
# src/utils/security.py — there's no gateway forwarding trusted headers
# anymore). None of these need to correspond to a real `employee` row: only
# endpoints that require a *linked* employee (timesheet submit/approve,
# current-employee update) reject a non-existent id, and those tests
# provision a real Employee via /admin/employees first.
ADMIN_ID = str(uuid.UUID(int=1))
AE_ID = str(uuid.UUID(int=2))
SALES_ID = str(uuid.UUID(int=3))
LEADERSHIP_ID = str(uuid.UUID(int=4))


def _bearer(employee_id: str, profile_code: str) -> dict:
    """Mints a real token via the same path real login uses
    (mint_token_for_profiles resolves capabilities from the DB-seeded
    role_capability table) — so these fixtures exercise the actual seeded
    grants, not a hand-maintained parallel copy of them."""
    return {"Authorization": f"Bearer {mint_token_for_profiles(employee_id, {profile_code})}"}


@pytest.fixture()
def admin_headers():
    return _bearer(ADMIN_ID, "ADMIN")


@pytest.fixture()
def ae_headers():
    return _bearer(AE_ID, "ACCOUNT_EXEC")


@pytest.fixture()
def sales_headers():
    return _bearer(SALES_ID, "SALES")


@pytest.fixture()
def leadership_headers():
    return _bearer(LEADERSHIP_ID, "LEADERSHIP")


@pytest.fixture(autouse=True, scope="session")
def _no_leftover_active_cadence_template():
    """create_lead() auto-enrolls a brand-new Lead into whichever
    CadenceTemplate is currently Active (crm_service._auto_enroll_new_lead())
    — against this suite's real, persistent Postgres DB (no per-test
    reset/rollback), a template left Active by an earlier test run would
    silently auto-enroll leads created by unrelated tests. Deactivating
    anything already Active once, at the very start of the session, gives
    every test a clean "no active cadence" starting point regardless of
    history; test_cadence.py's own fixture (see its
    _isolate_cadence_template_activation) keeps its many template-creating
    tests from leaking an Active template into tests that run after it."""
    client = TestClient(app)
    headers = _bearer(ADMIN_ID, "ADMIN")
    resp = client.get("/api/v1/cadence-templates", headers=headers)
    if resp.status_code == 200:
        for template in resp.json():
            if template.get("is_active"):
                client.patch(f"/api/v1/cadence-templates/{template['id']}",
                            json={"is_active": False}, headers=headers)
