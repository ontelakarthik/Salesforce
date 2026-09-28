"""Models for the Auth & RBAC module (§1/§3 of the API spec) — session,
current-employee profile, provisioning/linking, role resolution.

Auth owns no ORM tables of its own — it authenticates against the `employee`
/ `employee_role` tables provisioned by the Admin module (see
admin_models.py) and resolves permissions via src/utils/permissions.py. See
services/auth_service.py for the implementation.
"""
from pydantic import BaseModel, Field


class CurrentEmployeeOut(BaseModel):
    """§15 CurrentEmployee schema."""
    employee_id: str
    email: str | None = None
    full_name: str | None = None
    roles: list[str] = Field(default_factory=list)
    is_active: bool = True
    access_state: str  # ACTIVE | NO_ROLE | INACTIVE
    default_landing: str = "/dashboard"
    permissions: list[str] = Field(default_factory=list)


class CurrentEmployeeUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool
    employee: CurrentEmployeeOut


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=255)


class SetupAdminRequest(BaseModel):
    """Payload for POST /auth/setup-admin — the one-time first-run flow that
    replaces needing an operator to run scripts/bootstrap_admin.py by hand.
    Only ever succeeds once: see auth_service.setup_admin(), which rejects
    this outright the moment any employee already exists. Same shape as
    admin_models.EmployeeCreate (email + full_name only) — a temp password
    is generated and emailed, exactly like adding any other employee; there
    is deliberately no password field here."""
    email: str
    full_name: str = Field(min_length=1, max_length=255)


class SetupAdminOut(BaseModel):
    """temp_password is only ever populated when password_email_sent is
    False — the one-time-only guard means a failed email here would
    otherwise leave the account permanently unreachable, unlike a normal
    employee an admin can just re-provision."""
    email: str
    password_email_sent: bool
    temp_password: str | None = None
