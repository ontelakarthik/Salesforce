"""Auth & RBAC module (§1/§3) — real password login (no gateway/SSO in
front — see src/utils/security.py) + legacy Entra callback scaffold +
current-employee. Exercised against the real Postgres container.
"""
import re
import uuid

import pytest


def _extract_temp_password(email_body: str) -> str:
    match = re.search(r"Temporary password: (\S+)", email_body)
    assert match, f"couldn't find a temp password in the welcome email: {email_body!r}"
    return match.group(1)


class TestLogin:
    def test_login_succeeds_with_the_emailed_temp_password(self, client, admin_headers, sent_emails):
        email = f"login.{uuid.uuid4().hex[:8]}@example.com"
        client.post("/api/v1/admin/employees", json={"email": email, "full_name": "Login Case"},
                   headers=admin_headers)
        temp_password = _extract_temp_password(sent_emails[-1]["body"])

        r = client.post("/api/v1/auth/login", json={"email": email, "password": temp_password})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["must_change_password"] is True
        assert body["employee"]["email"] == email
        assert len(body["access_token"]) > 20

        # the minted token actually works against a real protected endpoint
        r2 = client.get("/api/v1/current-employee", headers={"Authorization": f"Bearer {body['access_token']}"})
        assert r2.status_code == 200, r2.text
        assert r2.json()["email"] == email

    def test_wrong_password_is_rejected(self, client, admin_headers, sent_emails):
        email = f"wrongpw.{uuid.uuid4().hex[:8]}@example.com"
        client.post("/api/v1/admin/employees", json={"email": email, "full_name": "Wrong PW Case"},
                   headers=admin_headers)

        r = client.post("/api/v1/auth/login", json={"email": email, "password": "not-the-right-password"})
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"

    def test_unknown_email_gets_the_same_generic_error(self, client):
        r = client.post("/api/v1/auth/login",
                        json={"email": f"nobody.{uuid.uuid4().hex[:8]}@example.com", "password": "whatever"})
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"

    def test_inactive_account_cannot_log_in(self, client, admin_headers, sent_emails):
        email = f"inactivelogin.{uuid.uuid4().hex[:8]}@example.com"
        emp = client.post("/api/v1/admin/employees", json={"email": email, "full_name": "Inactive Login"},
                         headers=admin_headers).json()
        temp_password = _extract_temp_password(sent_emails[-1]["body"])
        client.patch(f"/api/v1/admin/employees/{emp['id']}", json={"is_active": False}, headers=admin_headers)

        r = client.post("/api/v1/auth/login", json={"email": email, "password": temp_password})
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "ACCOUNT_INACTIVE"


class TestChangePassword:
    def _login(self, client, admin_headers, sent_emails, email):
        client.post("/api/v1/admin/employees", json={"email": email, "full_name": "Change PW Case"},
                   headers=admin_headers)
        temp_password = _extract_temp_password(sent_emails[-1]["body"])
        login = client.post("/api/v1/auth/login", json={"email": email, "password": temp_password}).json()
        return temp_password, {"Authorization": f"Bearer {login['access_token']}"}

    def test_change_password_clears_must_change_flag_and_new_password_works(
        self, client, admin_headers, sent_emails,
    ):
        email = f"changepw.{uuid.uuid4().hex[:8]}@example.com"
        temp_password, headers = self._login(client, admin_headers, sent_emails, email)

        r = client.post("/api/v1/auth/change-password",
                        json={"current_password": temp_password, "new_password": "a-new-strong-password"},
                        headers=headers)
        assert r.status_code == 204, r.text

        # old password no longer works, new one does
        assert client.post("/api/v1/auth/login",
                           json={"email": email, "password": temp_password}).status_code == 401
        r2 = client.post("/api/v1/auth/login", json={"email": email, "password": "a-new-strong-password"})
        assert r2.status_code == 200, r2.text
        assert r2.json()["must_change_password"] is False

    def test_wrong_current_password_is_rejected(self, client, admin_headers, sent_emails):
        email = f"wrongcurrent.{uuid.uuid4().hex[:8]}@example.com"
        _, headers = self._login(client, admin_headers, sent_emails, email)

        r = client.post("/api/v1/auth/change-password",
                        json={"current_password": "not-it", "new_password": "a-new-strong-password"},
                        headers=headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "CURRENT_PASSWORD_INCORRECT"


class TestWelcomeEmail:
    def test_create_employee_reports_whether_the_welcome_email_sent(self, client, admin_headers):
        email = f"welcome.{uuid.uuid4().hex[:8]}@example.com"
        r = client.post("/api/v1/admin/employees", json={"email": email, "full_name": "Welcome Case"},
                        headers=admin_headers)
        assert r.status_code == 201, r.text
        assert r.json()["password_email_sent"] is True  # captured by the autouse fake sender

    def test_email_send_failure_does_not_undo_employee_creation(self, client, admin_headers):
        from src.server import app
        from src.services.email_client import get_optional_email_sender
        app.dependency_overrides[get_optional_email_sender] = lambda: None
        try:
            email = f"noemail.{uuid.uuid4().hex[:8]}@example.com"
            r = client.post("/api/v1/admin/employees", json={"email": email, "full_name": "No Email Case"},
                            headers=admin_headers)
            assert r.status_code == 201, r.text
            assert r.json()["password_email_sent"] is False

            r2 = client.get("/api/v1/admin/employees", headers=admin_headers)
            assert any(e["email"] == email for e in r2.json())
        finally:
            app.dependency_overrides.pop(get_optional_email_sender, None)


class TestBearerTokenSecurity:
    """Regression coverage for the no-gateway security fix: raw
    X-Employee-Id/X-Roles headers must NOT grant access on their own
    anymore — only a validly signed bearer token does."""

    def test_raw_identity_headers_alone_grant_nothing(self, client):
        r = client.get("/api/v1/leads", headers={"X-Employee-Id": str(uuid.uuid4()), "X-Roles": "ADMIN"})
        # no bearer token -> falls through to DEV_AUTH_BYPASS in this test
        # env, but critically NOT as the spoofed identity/roles above.
        assert r.status_code == 200
        me = client.get("/api/v1/current-employee",
                        headers={"X-Employee-Id": str(uuid.uuid4()), "X-Roles": "ADMIN"}).json()
        assert me["employee_id"] == "dev-admin"

    def test_garbage_bearer_token_is_rejected(self, client):
        r = client.get("/api/v1/current-employee", headers={"Authorization": "Bearer not-a-real-jwt"})
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "INVALID_TOKEN"

    def test_token_signed_with_a_different_secret_is_rejected(self, client):
        import jwt as pyjwt
        forged = pyjwt.encode({"employee_id": str(uuid.uuid4()), "roles": ["ADMIN"]},
                              "wrong-secret-but-long-enough-to-not-warn", algorithm="HS256")
        r = client.get("/api/v1/current-employee", headers={"Authorization": f"Bearer {forged}"})
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "INVALID_TOKEN"


class TestSsoCallback:
    """Legacy scaffold — dormant now there's no gateway to front an Entra
    redirect (see config.py's GATEWAY_CALLBACK_SECRET comment), kept working
    in case SSO is wired up again later."""

    def test_no_account_provisioned_yet_is_rejected(self, client):
        r = client.get("/api/v1/auth/callback", params={
            "entra_object_id": f"entra-{uuid.uuid4()}",
            "email": f"unprovisioned.{uuid.uuid4().hex[:8]}@example.com",
            "full_name": "Nobody",
        })
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "NO_ACCOUNT"

    def test_first_login_links_entra_identity_by_email(self, client, admin_headers):
        email = f"newhire.{uuid.uuid4().hex[:8]}@example.com"
        client.post("/api/v1/admin/employees", json={"email": email, "full_name": "New Hire"},
                   headers=admin_headers)

        entra_id = f"entra-{uuid.uuid4()}"
        r = client.get("/api/v1/auth/callback",
                       params={"entra_object_id": entra_id, "email": email, "full_name": "New Hire"})
        assert r.status_code == 200
        body = r.json()
        assert body["email"] == email
        assert body["access_state"] == "NO_ROLE"  # no roles granted yet

    def test_identity_conflict_when_email_already_linked_elsewhere(self, client, admin_headers):
        email = f"conflict.{uuid.uuid4().hex[:8]}@example.com"
        client.post("/api/v1/admin/employees", json={"email": email, "full_name": "Conflict Case"},
                   headers=admin_headers)
        first_entra_id = f"entra-{uuid.uuid4()}"
        client.get("/api/v1/auth/callback",
                  params={"entra_object_id": first_entra_id, "email": email, "full_name": "Conflict Case"})

        r = client.get("/api/v1/auth/callback", params={
            "entra_object_id": f"entra-{uuid.uuid4()}", "email": email, "full_name": "Conflict Case",
        })
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "IDENTITY_CONFLICT"

    def test_inactive_account_is_rejected(self, client, admin_headers):
        email = f"inactive.{uuid.uuid4().hex[:8]}@example.com"
        emp = client.post("/api/v1/admin/employees", json={"email": email, "full_name": "Inactive Case"},
                         headers=admin_headers).json()
        client.patch(f"/api/v1/admin/employees/{emp['id']}", json={"is_active": False},
                    headers=admin_headers)

        r = client.get("/api/v1/auth/callback",
                       params={"entra_object_id": f"entra-{uuid.uuid4()}", "email": email, "full_name": ""})
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "ACCOUNT_INACTIVE"


class TestCurrentEmployee:
    def test_dev_bypass_identity_has_no_linked_employee_record(self, client):
        r = client.get("/api/v1/current-employee")  # no token -> DEV_AUTH_BYPASS
        assert r.status_code == 200
        body = r.json()
        assert body["employee_id"] == "dev-admin"
        assert body["email"] is None
        assert "ADMIN" in body["roles"]

    def test_update_requires_a_linked_employee(self, client):
        r = client.patch("/api/v1/current-employee", json={"full_name": "New Name"})
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "NO_LINKED_EMPLOYEE"

    def test_update_succeeds_for_a_real_linked_employee(self, client, admin_headers):
        from src.services.auth_service import mint_token_for_profiles

        email = f"selfupdate.{uuid.uuid4().hex[:8]}@example.com"
        emp = client.post("/api/v1/admin/employees", json={"email": email, "full_name": "Old Name"},
                         headers=admin_headers).json()
        headers = {"Authorization": f"Bearer {mint_token_for_profiles(emp['id'], {'ADMIN'})}"}

        r = client.patch("/api/v1/current-employee", json={"full_name": "Updated Name"}, headers=headers)
        assert r.status_code == 200
        assert r.json()["full_name"] == "Updated Name"


class TestSetupAdmin:
    """The happy path (creating the very first admin against a genuinely
    empty employee table) can't be exercised via HTTP here — this suite
    runs against a persistent shared Postgres with no per-test rollback, so
    by the time any test runs the table already has rows from every earlier
    test. See the fake-based unit tests below, which test
    auth_service.setup_admin() directly. The guard behavior here, on the
    other hand, is exactly as easy to prove for real: it's the property
    that matters most (this can never become a second way to create an
    admin once one exists)."""

    def test_rejected_once_any_employee_exists(self, client, admin_headers):
        client.post("/api/v1/admin/employees",
                   json={"email": f"guard.{uuid.uuid4().hex[:8]}@example.com", "full_name": "Guard"},
                   headers=admin_headers)
        r = client.post("/api/v1/auth/setup-admin",
                        json={"email": f"newadmin.{uuid.uuid4().hex[:8]}@example.com", "full_name": "New Admin"})
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "SETUP_ALREADY_COMPLETED"


class _FakeEmployeeRepo:
    def __init__(self):
        self.created = None

    def list(self):
        return []  # the precondition this whole feature exists to check

    def create(self, **kwargs):
        import uuid as uuid_mod
        from types import SimpleNamespace
        self.created = SimpleNamespace(id=uuid_mod.uuid4(), is_active=True, **kwargs)
        return self.created


class _FakeRoleRepo:
    def list(self, code):
        from types import SimpleNamespace
        assert code == "ADMIN"
        return [SimpleNamespace(id=1, code="ADMIN")]


class _FakeEmployeeRoleRepo:
    def __init__(self):
        self.granted = None

    def grant(self, employee_id, role_id, granted_by=None):
        self.granted = (employee_id, role_id, granted_by)


def _patch_setup_admin_repos(monkeypatch):
    from src.services import auth_service
    fake_employees, fake_roles, fake_employee_roles = _FakeEmployeeRepo(), _FakeRoleRepo(), _FakeEmployeeRoleRepo()
    monkeypatch.setattr(auth_service, "get_employee_repository", lambda: fake_employees)
    monkeypatch.setattr(auth_service, "get_profile_repository", lambda: fake_roles)
    monkeypatch.setattr(auth_service, "get_employee_role_repository", lambda: fake_employee_roles)
    return fake_employees, fake_roles, fake_employee_roles


def test_setup_admin_creates_the_first_admin_and_emails_a_temp_password(monkeypatch):
    from src.models import auth_models
    from src.services import auth_service

    fake_employees, _, fake_employee_roles = _patch_setup_admin_repos(monkeypatch)

    class _FakeSender:
        def __init__(self):
            self.sent = []

        def send(self, to_address, subject, body):
            self.sent.append((to_address, subject, body))

    fake_sender = _FakeSender()
    result = auth_service.setup_admin(
        auth_models.SetupAdminRequest(email="First.Admin@example.com", full_name="First Admin"),
        fake_sender)

    assert result.email == "first.admin@example.com"
    assert result.password_email_sent is True
    assert result.temp_password is None  # only surfaced when the email fails to send
    assert fake_employees.created.must_change_password is True
    assert fake_employee_roles.granted == (fake_employees.created.id, 1, "setup")
    assert fake_sender.sent[0][0] == "first.admin@example.com"


def test_setup_admin_surfaces_the_temp_password_when_email_fails(monkeypatch):
    from src.models import auth_models
    from src.services import auth_service
    from src.utils.exceptions import DomainError

    _patch_setup_admin_repos(monkeypatch)

    class _FailingSender:
        def send(self, to_address, subject, body):
            raise DomainError("EMAIL_SEND_FAILED", "simulated failure", 502)

    result = auth_service.setup_admin(
        auth_models.SetupAdminRequest(email="second.admin@example.com", full_name="Second Admin"),
        _FailingSender())

    assert result.password_email_sent is False
    assert result.temp_password is not None  # the one door out of a permanent lockout


def test_setup_admin_rejects_when_an_employee_already_exists(monkeypatch):
    from types import SimpleNamespace

    from src.models import auth_models
    from src.services import auth_service
    from src.utils.exceptions import DomainError

    class _NonEmptyEmployeeRepo:
        def list(self):
            return [SimpleNamespace(id="whatever")]

    monkeypatch.setattr(auth_service, "get_employee_repository", lambda: _NonEmptyEmployeeRepo())

    with pytest.raises(DomainError) as exc_info:
        auth_service.setup_admin(
            auth_models.SetupAdminRequest(email="late@example.com", full_name="Too Late"), None)
    assert exc_info.value.code == "SETUP_ALREADY_COMPLETED"
