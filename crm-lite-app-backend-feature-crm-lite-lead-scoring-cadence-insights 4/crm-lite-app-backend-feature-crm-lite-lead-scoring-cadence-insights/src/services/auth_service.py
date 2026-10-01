"""Auth & RBAC module business logic (§1/§3/§3.1 of the API spec) — session,
current-employee profile, provisioning/linking, role resolution.

`GET /auth/callback` implements the Pattern-A resolution flow:
1. Validate the Entra SSO assertion — done upstream by the gateway; this
   service trusts the entra_object_id/email/full_name it's given.
2. Look up employee by entra_object_id.
   - Found -> proceed to step 4.
   - Not found -> look up by email (case-insensitive).
     - Found, entra_object_id is null -> first login: stamp entra_object_id
       (link), then proceed.
     - Found, already linked to a different entra_object_id -> 403 IDENTITY_CONFLICT.
     - Not found by email either -> 403 NO_ACCOUNT (Pattern A never auto-creates).
3. (linking done)
4. If employee.is_active = false -> 403 ACCOUNT_INACTIVE.
5. Resolve roles from employee_role. Zero roles -> access_state=NO_ROLE;
   otherwise -> access_state=ACTIVE.

Auth never verifies tokens itself in this deployment — identity is
gateway-trusted (see src/utils/security.py); this module's job is resolving
that identity into a CurrentEmployee profile + permissions map.
"""
from uuid import UUID

from src.models import auth_models
from src.repositories._base import resolve_lookup_id
from src.repositories.admin_repository import (
    get_employee_repository,
    get_employee_role_repository,
    get_profile_repository,
    get_role_capability_repository,
)
from src.services.email_client import EmailSender
from src.utils.error_handling import handle_errors
from src.utils.exceptions import DomainError
from src.utils.passwords import generate_temp_password, hash_password, verify_password
from src.utils.security import CurrentUser, mint_access_token


def _role_codes_for_employee(employee_id: UUID) -> list[str]:
    profile_repo = get_profile_repository()
    rows = get_employee_role_repository().list_for_employee(employee_id)
    return [profile_repo.get(r.role_id).code for r in rows]


def _permissions_for(role_codes: set[str]) -> list[str]:
    """Union of every capability granted (via role_capability) to any of the
    given profile codes — DB-driven, same "computed once, at login" shape
    the old static-CAPABILITIES-dict version had."""
    profile_repo = get_profile_repository()
    cap_repo = get_role_capability_repository()
    profile_ids = {row.id for row in profile_repo.list() if row.code in role_codes}
    keys = {row.capability_key for pid in profile_ids for row in cap_repo.list_for_role(pid)}
    return sorted(keys)


def mint_token_for_profiles(employee_id: str, profile_codes: set[str]) -> str:
    """Resolves capabilities for the given profile codes from the DB and
    mints a token — the one path (real login and tests both use this) that
    guarantees a token's `capabilities` claim always matches what its
    `profile_codes` are actually granted."""
    return mint_access_token(employee_id, profile_codes, set(_permissions_for(profile_codes)))


@handle_errors("log out")
def logout() -> dict:
    """Session lifecycle is gateway-managed; there's nothing for this
    service to invalidate server-side."""
    return {"message": "Logged out. The gateway session, if any, should be "
                       "cleared by the client/gateway."}


@handle_errors("process the SSO callback")
def handle_sso_callback(entra_object_id: str, email: str,
                        full_name: str) -> auth_models.CurrentEmployeeOut:
    emp_repo = get_employee_repository()
    employee = emp_repo.find_by_entra_object_id(entra_object_id)
    if employee is None:
        employee = emp_repo.find_by_email(email)
        if employee is None:
            raise DomainError("NO_ACCOUNT",
                              "No employee account has been provisioned for this identity.", 403)
        if employee.entra_object_id is not None and employee.entra_object_id != entra_object_id:
            raise DomainError("IDENTITY_CONFLICT",
                              "This email is already linked to a different identity.", 403)
        if employee.entra_object_id is None:
            employee = emp_repo.update(employee.id, entra_object_id=entra_object_id,
                                       full_name=full_name or employee.full_name)

    if not employee.is_active:
        raise DomainError("ACCOUNT_INACTIVE", "This account has been deactivated.", 403)

    role_codes = _role_codes_for_employee(employee.id)
    return auth_models.CurrentEmployeeOut(
        employee_id=str(employee.id), email=employee.email, full_name=employee.full_name,
        roles=role_codes, is_active=employee.is_active,
        access_state="ACTIVE" if role_codes else "NO_ROLE",
        permissions=_permissions_for(set(role_codes)),
    )


def _login_out(employee, role_codes: list[str]) -> auth_models.LoginOut:
    token = mint_token_for_profiles(str(employee.id), set(role_codes))
    employee_out = auth_models.CurrentEmployeeOut(
        employee_id=str(employee.id), email=employee.email, full_name=employee.full_name,
        roles=role_codes, is_active=employee.is_active,
        access_state="ACTIVE" if role_codes else "NO_ROLE",
        permissions=_permissions_for(set(role_codes)),
    )
    return auth_models.LoginOut(
        access_token=token, must_change_password=employee.must_change_password, employee=employee_out)


@handle_errors("log in")
def login(payload: auth_models.LoginRequest) -> auth_models.LoginOut:
    """No gateway/SSO in front anymore — this is the real authentication
    boundary. Deliberately generic on failure (INVALID_CREDENTIALS covers
    unknown email, wrong password, AND "no password set yet") rather than
    distinguishing them, so a login attempt can't be used to enumerate which
    emails have accounts."""
    employee = get_employee_repository().find_by_email(payload.email.strip().lower())
    if (employee is None or employee.password_hash is None
            or not verify_password(payload.password, employee.password_hash)):
        raise DomainError("INVALID_CREDENTIALS", "Incorrect email or password.", 401)
    if not employee.is_active:
        raise DomainError("ACCOUNT_INACTIVE", "This account has been deactivated.", 403)
    return _login_out(employee, _role_codes_for_employee(employee.id))


@handle_errors("set up admin")
def setup_admin(payload: auth_models.SetupAdminRequest,
                email_sender: EmailSender | None) -> auth_models.SetupAdminOut:
    """One-time first-run flow: creates the very first ADMIN account,
    self-provisioned through the UI instead of an operator running
    scripts/bootstrap_admin.py by hand. Only reachable when NO employee
    exists yet anywhere — the moment one does (this call or any other way),
    every future call permanently 409s, so this can never become a general
    "anyone can sign up as admin" hole.

    Deliberately mirrors admin_service.create_employee(): a system-generated
    temp password, emailed, must_change_password=True — the same
    email-a-temp-password-then-force-a-change flow every other employee
    goes through, rather than a separate "set your own password here" path.
    """
    emp_repo = get_employee_repository()
    if emp_repo.list():
        raise DomainError(
            "SETUP_ALREADY_COMPLETED",
            "An account already exists — sign in instead of setting one up again.", 409)

    email = payload.email.strip().lower()
    temp_password = generate_temp_password()
    employee = emp_repo.create(
        email=email, full_name=payload.full_name,
        password_hash=hash_password(temp_password), must_change_password=True,
        created_by="setup", updated_by="setup",
    )
    admin_role_id = resolve_lookup_id(get_profile_repository(), "ADMIN", "ROLE_NOT_FOUND", "role code")
    get_employee_role_repository().grant(employee.id, admin_role_id, granted_by="setup")

    password_email_sent = False
    if email_sender is not None:
        try:
            email_sender.send(
                email, "Your CRM Lite account",
                f"Hi {employee.full_name},\n\n"
                "Your CRM Lite administrator account has been created.\n\n"
                f"Login email: {email}\n"
                f"Temporary password: {temp_password}\n\n"
                "You'll be asked to set your own password the first time you log in.",
            )
            password_email_sent = True
        except DomainError:
            pass  # surfaced via temp_password below — this account must stay reachable
    return auth_models.SetupAdminOut(
        email=email, password_email_sent=password_email_sent,
        temp_password=None if password_email_sent else temp_password)


@handle_errors("change password")
def change_password(user: CurrentUser, payload: auth_models.ChangePasswordRequest) -> None:
    try:
        employee_id = UUID(user.employee_id)
    except ValueError as exc:
        raise DomainError(
            "NO_LINKED_EMPLOYEE",
            "This identity isn't linked to an employee record yet.", 409) from exc
    repo = get_employee_repository()
    employee = repo.get(employee_id)
    if employee is None:
        raise DomainError("EMPLOYEE_NOT_FOUND", "Linked employee record not found.", 404)
    if employee.password_hash is None or not verify_password(payload.current_password, employee.password_hash):
        raise DomainError("CURRENT_PASSWORD_INCORRECT", "The current password is incorrect.", 422)
    repo.update(
        employee_id, password_hash=hash_password(payload.new_password), must_change_password=False,
        updated_by=user.employee_id,
    )


@handle_errors("get current employee")
def get_current_employee(user: CurrentUser) -> auth_models.CurrentEmployeeOut:
    """Roles come from the gateway-asserted CurrentUser (the same source
    every RBAC check uses), not re-derived from the DB, so this always
    matches what the caller is actually authorized to do this request."""
    employee = None
    try:
        employee = get_employee_repository().get(UUID(user.employee_id))
    except ValueError:
        pass  # not a UUID (e.g. DEV_AUTH_BYPASS's "dev-admin") — no linked row

    role_codes = list(user.profile_codes)
    is_active = employee.is_active if employee is not None else True
    if not role_codes:
        access_state = "NO_ROLE"
    elif not is_active:
        access_state = "INACTIVE"
    else:
        access_state = "ACTIVE"

    return auth_models.CurrentEmployeeOut(
        employee_id=user.employee_id,
        email=employee.email if employee is not None else None,
        full_name=employee.full_name if employee is not None else None,
        roles=role_codes, is_active=is_active, access_state=access_state,
        permissions=_permissions_for(set(role_codes)),
    )


@handle_errors("update current employee")
def update_current_employee(user: CurrentUser,
                            payload: auth_models.CurrentEmployeeUpdate) -> auth_models.CurrentEmployeeOut:
    try:
        employee_id = UUID(user.employee_id)
    except ValueError as exc:
        raise DomainError(
            "NO_LINKED_EMPLOYEE",
            "This identity isn't linked to an employee record yet.", 409) from exc
    repo = get_employee_repository()
    if repo.get(employee_id) is None:
        raise DomainError("EMPLOYEE_NOT_FOUND", "Linked employee record not found.", 404)
    changes = payload.model_dump(exclude_unset=True)
    if changes:
        changes["updated_by"] = user.employee_id
        repo.update(employee_id, **changes)
    return get_current_employee(user)
