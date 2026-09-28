"""Admin module business logic (§1/§13.5 of the API spec) — employee
provisioning, role assignment, teams/DLs, lookup value management.

Rules enforced:
- Pattern-A provisioning: Admin pre-creates the employee row (entra_object_id
  always null here); the Auth module's SSO callback links the Entra identity
  on first login (see auth_service.py).
- Employee email is unique (DB constraint) and is never changed via update.
- Profiles are set only via set_employee_profiles() (never as part of
  employee create/update) — a full replace of the profile set, not an
  incremental patch.
- Lookup `code` is immutable after create (not part of LookupUpdate) and
  unique (DB constraint). Deleting a lookup value that's still referenced by
  another table is blocked — enforced by the DB's own FK constraint, caught
  here and translated into a 409 LOOKUP_IN_USE.
"""
from collections.abc import Callable
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from src.models import admin_models
from src.repositories._base import CrudRepository, resolve_lookup_id
from src.repositories.activity_repository import get_call_disposition_repository
from src.repositories.admin_repository import (
    get_employee_repository,
    get_employee_role_repository,
    get_profile_repository,
    get_role_capability_repository,
    get_team_repository,
    get_territory_repository,
)
from src.repositories.contracts_repository import (
    get_agreement_status_repository,
    get_agreement_type_repository,
)
from src.repositories.crm_repository import (
    get_contact_type_repository,
    get_account_type_repository,
    get_opportunity_stage_repository,
)
from src.repositories.project_repository import get_project_status_repository
from src.services.email_client import EmailSender
from src.utils import geo
from src.utils.error_handling import handle_errors
from src.utils.exceptions import DomainError
from src.utils.passwords import generate_temp_password, hash_password
from src.utils.permissions import CAPABILITY_REGISTRY
from src.utils.security import CurrentUser

# "role" is deliberately NOT here: Profile (the role table's Python-level
# name now — see admin_models.Profile) has its own dedicated CRUD below
# (list/create/update/delete_profile + capability-matrix endpoints) instead
# of the generic lookup path every other reference table uses. It used to be
# generic, and that's exactly why creating a 5th role through it silently
# locked its holder out — a profile created this way skipped is_system
# defaulting and never got a capability grant. One path now, not two.
_LOOKUP_TABLES: dict[str, Callable[[], CrudRepository]] = {
    "account_type": get_account_type_repository,
    "contact_type": get_contact_type_repository,
    "opportunity_stage": get_opportunity_stage_repository,
    "agreement_type": get_agreement_type_repository,
    "agreement_status": get_agreement_status_repository,
    "project_status": get_project_status_repository,
    "call_disposition": get_call_disposition_repository,
    # Sales Territory/Region (see admin_models.Territory) — reuses this same
    # generic lookup CRUD rather than bespoke endpoints; is_active is the one
    # field only this table has (see _lookup_fields()'s hasattr filtering).
    "territory": get_territory_repository,
}

_TERRITORY_TABLE = "territory"


def _lookup_repo(table: str) -> CrudRepository:
    factory = _LOOKUP_TABLES.get(table)
    if factory is None:
        raise DomainError(
            "LOOKUP_TABLE_NOT_FOUND",
            f"Unknown lookup table '{table}'. Valid tables: {', '.join(_LOOKUP_TABLES)}.", 404)
    return factory()


def _lookup_fields(repo: CrudRepository, payload: BaseModel) -> dict:
    """Only forward the columns the target lookup table actually has (e.g.
    default_sla_hours only applies to agreement_type)."""
    return {k: v for k, v in payload.model_dump(exclude_unset=True).items()
            if hasattr(repo.model, k)}


def _validate_territory_fields(fields: dict, *, current, territory_id: int | None = None) -> None:
    """Territory-only required/valid-value rules the shared LookupCreate/
    LookupUpdate schema can't express per-table: Name and Status are already
    required at the schema layer for every table; Country is required only
    for Territory (meaningless for the other 6 lookup tables sharing this
    endpoint). Region is optional, unlike Country — a country-wide/top-level
    territory (e.g. "USA" itself) legitimately has no single region — but
    when given, must belong to the given Country's existing Region
    vocabulary (see utils.geo.valid_regions() — reused as-is, never a second
    Region concept). `current` is the existing row on an update (so a
    partial payload that omits country/region is validated against its
    already-stored value, and country can't be cleared to blank), or None on
    create. `territory_id` is this row's own id (None on create, since a
    brand-new row can't already be its own ancestor) — passed through to
    _validate_territory_parent() for cycle detection."""
    country = fields["country"] if "country" in fields else (current.country if current else None)
    region = fields["region"] if "region" in fields else (current.region if current else None)
    if not country:
        raise DomainError("COUNTRY_REQUIRED", "country is required for a territory.", 422)
    geo.validate_country_state_province(country, None)
    if region:
        valid = geo.valid_regions(country)
        if region not in valid:
            raise DomainError(
                "INVALID_REGION",
                f"'{region}' is not a valid region for {country}. Valid regions: {', '.join(valid)}.", 422)
    if "parent_territory_id" in fields:
        _validate_territory_parent(get_territory_repository(), territory_id, fields["parent_territory_id"])
    if current is None and ("is_active" not in fields or fields["is_active"] is None):
        raise DomainError("STATUS_REQUIRED", "status is required for a territory.", 422)


def _validate_territory_parent(repo, territory_id: int | None, new_parent_id: int | None) -> None:
    """Mirrors _validate_new_parent() (Profile's Role Hierarchy cycle
    detection) exactly, applied to Territory.parent_territory_id instead —
    same in-memory tree-walk approach, same reasoning (the territory table
    is small). territory_id is None on create, where a cycle is impossible
    (a brand-new row can't already be its own ancestor) — only new_parent_id's
    existence is checked in that case."""
    if new_parent_id is None:
        return
    if territory_id is not None and new_parent_id == territory_id:
        raise DomainError("TERRITORY_HIERARCHY_CYCLE", "A territory can't be its own parent.", 422)
    by_id = {t.id: t for t in repo.list()}
    if new_parent_id not in by_id:
        raise DomainError("TERRITORY_NOT_FOUND", f"No territory '{new_parent_id}'.", 422)
    if territory_id is None:
        return
    cursor = new_parent_id
    seen: set[int] = set()
    while cursor is not None:
        if cursor == territory_id:
            raise DomainError(
                "TERRITORY_HIERARCHY_CYCLE",
                "This would create a cycle in the territory hierarchy.", 422)
        if cursor in seen:
            break  # defensive only — the tree shouldn't already have a cycle
        seen.add(cursor)
        cursor = by_id[cursor].parent_territory_id if cursor in by_id else None


def verified_employee_uuid(user: CurrentUser) -> UUID | None:
    """CurrentUser.employee_uuid() only checks that the gateway-forwarded
    identity parses as a UUID; every other module that auto-derives an
    employee FK from the acting user (signed_by_employee_id,
    reviewer_employee_id, logged_by_employee_id, timesheet submitted_by/
    approved_by, ...) calls this instead, so a syntactically-valid but
    unprovisioned identity (roles asserted by the gateway, but Admin hasn't
    created the Employee row yet — see Pattern-A provisioning above) resolves
    to None rather than raising a raw IntegrityError on write."""
    employee_uuid = user.employee_uuid()
    if employee_uuid is None:
        return None
    return employee_uuid if get_employee_repository().get(employee_uuid) is not None else None


def _validate_new_employee_territory(territory_id: int | None) -> None:
    """Called only when territory_id is actually present in the request
    (a NEW/changed assignment) — never on every read/unrelated-field update,
    so a territory that's since been deactivated doesn't retroactively break
    an employee who was already assigned it (existing assignments are
    preserved; only a *new* assignment must target something that exists
    and is currently active). None (clearing the assignment) is always
    allowed, same "None means unset" as every other optional FK field."""
    if territory_id is None:
        return
    territory = get_territory_repository().get(territory_id)
    if territory is None:
        raise DomainError("TERRITORY_NOT_FOUND", f"No territory '{territory_id}'.", 422)
    if not territory.is_active:
        raise DomainError(
            "TERRITORY_INACTIVE", "Cannot assign an inactive territory.", 422)


def employee_ids_with_role(role_code: str) -> list[UUID]:
    """Active employees holding the given role — e.g. every current
    LEADERSHIP employee, for modules that need to broadcast a notification
    to a whole role rather than one specific person."""
    role_id = resolve_lookup_id(get_profile_repository(), role_code, "ROLE_NOT_FOUND", "role code")
    holder_ids = {r.employee_id for r in get_employee_role_repository().list_for_role(role_id)}
    return [e.id for e in get_employee_repository().list() if e.id in holder_ids and e.is_active]


# --- Employees ---------------------------------------------------------------
def _employee_out(employee, role_map: dict[int, str] | None = None,
                  territory_map: dict[int, str] | None = None) -> admin_models.EmployeeOut:
    role_rows = get_employee_role_repository().list_for_employee(employee.id)
    codes_by_id = role_map if role_map is not None else {r.id: r.code for r in get_profile_repository().list()}
    codes = [codes_by_id[r.role_id] for r in role_rows]
    # {territory.id: display_name} — for the UI's benefit only (territory_id
    # itself is the actual relationship, always passed through as-is below).
    # Never keyed/valued by code, which is optional and can be null.
    names_by_id = (
        territory_map if territory_map is not None
        else {t.id: t.display_name for t in get_territory_repository().list()})
    return admin_models.EmployeeOut(
        id=employee.id, entra_object_id=employee.entra_object_id, email=employee.email,
        full_name=employee.full_name, is_active=employee.is_active,
        must_change_password=employee.must_change_password, roles=codes,
        territory_id=employee.territory_id,
        territory_name=names_by_id.get(employee.territory_id),
        created_at=employee.created_at, updated_at=employee.updated_at,
        created_by=employee.created_by, updated_by=employee.updated_by,
    )


@handle_errors("list employees")
def list_employees() -> list[admin_models.EmployeeOut]:
    role_map = {r.id: r.code for r in get_profile_repository().list()}
    territory_map = {t.id: t.display_name for t in get_territory_repository().list()}
    return [_employee_out(e, role_map, territory_map) for e in get_employee_repository().list()]


@handle_errors("list employee directory")
def list_employee_directory() -> list[admin_models.EmployeeDirectoryEntry]:
    """Every employee, active or not — a deactivated employee can still be
    the historical signer/reviewer/owner on an old record, and that name
    shouldn't go blank just because they left."""
    return [admin_models.EmployeeDirectoryEntry(id=e.id, full_name=e.full_name)
           for e in get_employee_repository().list()]


@handle_errors("get employee")
def get_employee(employee_id: UUID) -> admin_models.EmployeeOut:
    employee = get_employee_repository().get(employee_id)
    if employee is None:
        raise DomainError("EMPLOYEE_NOT_FOUND", f"No employee '{employee_id}'.", 404)
    return _employee_out(employee)


@handle_errors("create employee")
def create_employee(user: CurrentUser, email_sender: EmailSender | None,
                    payload: admin_models.EmployeeCreate) -> admin_models.EmployeeCreateOut:
    """Provisions the employee with a system-generated temp password
    (must_change_password=True) and emails it to them. email_sender is None
    when SMTP isn't configured, and a send failure is caught too — neither
    undoes the employee's creation, it's reflected in the response's
    password_email_sent so an admin can share the credential another way;
    see EmployeeCreateOut."""
    _validate_new_employee_territory(payload.territory_id)
    repo = get_employee_repository()
    temp_password = generate_temp_password()
    employee = repo.create(
        email=payload.email.strip().lower(), full_name=payload.full_name,
        password_hash=hash_password(temp_password), must_change_password=True,
        territory_id=payload.territory_id,
        created_by=user.employee_id, updated_by=user.employee_id,
    )

    password_email_sent = False
    if email_sender is not None:
        try:
            email_sender.send(
                employee.email, "Your CRM Lite account",
                f"Hi {employee.full_name},\n\n"
                "An account has been created for you in CRM Lite.\n\n"
                f"Login email: {employee.email}\n"
                f"Temporary password: {temp_password}\n\n"
                "You'll be asked to set your own password the first time you log in.",
            )
            password_email_sent = True
        except DomainError:
            pass  # send failed — surfaced via the flag below, not a hard failure

    out = _employee_out(employee)
    return admin_models.EmployeeCreateOut(**out.model_dump(), password_email_sent=password_email_sent)


@handle_errors("update employee")
def update_employee(user: CurrentUser, employee_id: UUID,
                    payload: admin_models.EmployeeUpdate) -> admin_models.EmployeeOut:
    repo = get_employee_repository()
    if repo.get(employee_id) is None:
        raise DomainError("EMPLOYEE_NOT_FOUND", f"No employee '{employee_id}'.", 404)
    changes = payload.model_dump(exclude_unset=True)
    if "territory_id" in changes:
        _validate_new_employee_territory(changes["territory_id"])
    changes["updated_by"] = user.employee_id
    updated = repo.update(employee_id, **changes)
    return _employee_out(updated)


@handle_errors("set employee profiles")
def set_employee_profiles(user: CurrentUser, employee_id: UUID,
                          payload: admin_models.EmployeeProfilesUpdate) -> admin_models.EmployeeOut:
    """Full replace: the employee ends up with exactly these profile codes."""
    emp_repo = get_employee_repository()
    if emp_repo.get(employee_id) is None:
        raise DomainError("EMPLOYEE_NOT_FOUND", f"No employee '{employee_id}'.", 404)

    profile_repo = get_profile_repository()
    role_ids = [resolve_lookup_id(profile_repo, code, "ROLE_NOT_FOUND", "profile code")
               for code in payload.profile_codes]

    er_repo = get_employee_role_repository()
    current = {r.role_id for r in er_repo.list_for_employee(employee_id)}
    wanted = set(role_ids)
    for role_id in current - wanted:
        er_repo.revoke(employee_id, role_id)
    for role_id in wanted - current:
        er_repo.grant(employee_id, role_id, granted_by=user.employee_id)

    return _employee_out(emp_repo.get(employee_id))


# --- Profiles (admin-configurable RBAC bundles) -------------------------------
# Profile is the Python/API-level name for what the `role` table now models —
# see admin_models.Profile's docstring. is_system protects the 4 originally-
# seeded profiles from delete/rename; capability grants (role_capability) are
# a separate full-replace matrix, mirroring crm_service.py's FLS save shape.


@handle_errors("list profiles")
def list_profiles() -> list[admin_models.ProfileOut]:
    return [admin_models.ProfileOut.model_validate(r) for r in get_profile_repository().list()]


@handle_errors("create profile")
def create_profile(payload: admin_models.ProfileCreate) -> admin_models.ProfileOut:
    repo = get_profile_repository()
    try:
        row = repo.create(code=payload.code.strip().upper(), display_name=payload.display_name,
                          is_system=False)
    except IntegrityError as exc:
        raise DomainError(
            "PROFILE_CODE_TAKEN", f"A profile with code '{payload.code}' already exists.", 409) from exc
    return admin_models.ProfileOut.model_validate(row)


@handle_errors("update profile")
def update_profile(profile_id: int, payload: admin_models.ProfileUpdate) -> admin_models.ProfileOut:
    repo = get_profile_repository()
    if repo.get(profile_id) is None:
        raise DomainError("PROFILE_NOT_FOUND", f"No profile '{profile_id}'.", 404)
    changes = payload.model_dump(exclude_unset=True)
    if "parent_role_id" in changes:
        _validate_new_parent(repo, profile_id, changes["parent_role_id"])
    updated = repo.update(profile_id, **changes) if changes else repo.get(profile_id)
    return admin_models.ProfileOut.model_validate(updated)


def _validate_new_parent(repo, profile_id: int, new_parent_id: int | None) -> None:
    """Reject a parent_role_id change that would self-parent a profile,
    point at a nonexistent profile, or create a cycle in the Role Hierarchy
    tree. The whole `role` table is tiny (a handful to a few dozen rows even
    with many custom profiles), so loading it once and walking the
    in-memory parent map is cheap and simple — same style as the FLS/
    capability validation elsewhere in this file."""
    if new_parent_id is None:
        return
    if new_parent_id == profile_id:
        raise DomainError("PROFILE_HIERARCHY_CYCLE", "A profile can't be its own parent.", 422)
    by_id = {p.id: p for p in repo.list()}
    if new_parent_id not in by_id:
        raise DomainError("PROFILE_NOT_FOUND", f"No profile '{new_parent_id}'.", 404)
    cursor = new_parent_id
    seen: set[int] = set()
    while cursor is not None:
        if cursor == profile_id:
            raise DomainError(
                "PROFILE_HIERARCHY_CYCLE",
                "This would create a cycle in the profile hierarchy.", 422)
        if cursor in seen:
            break  # defensive only — the tree shouldn't already have a cycle
        seen.add(cursor)
        cursor = by_id[cursor].parent_role_id if cursor in by_id else None


@handle_errors("delete profile")
def delete_profile(profile_id: int) -> None:
    repo = get_profile_repository()
    row = repo.get(profile_id)
    if row is None:
        raise DomainError("PROFILE_NOT_FOUND", f"No profile '{profile_id}'.", 404)
    if row.code == "ADMIN":
        # Unlike the other 3 built-ins, ADMIN has no recovery path if it's
        # ever deleted: /auth/setup-admin and scripts/bootstrap_admin.py both
        # look up an existing row by code, neither creates one, and its only
        # seed is a one-time migration Alembic won't rerun. SALES/
        # ACCOUNT_EXEC/LEADERSHIP don't have this problem, so only ADMIN
        # stays permanently protected — everything else is just a normal
        # profile once PROFILE_IN_USE/PROFILE_IS_PARENT below are satisfied.
        raise DomainError("PROFILE_IS_SYSTEM", "The built-in Admin profile can't be deleted.", 422)
    if get_employee_role_repository().list_for_role(profile_id):
        raise DomainError(
            "PROFILE_IN_USE", "This profile is still assigned to at least one employee.", 409)
    if any(p.parent_role_id == profile_id for p in repo.list()):
        raise DomainError(
            "PROFILE_IS_PARENT",
            "Other profiles report to this one in the hierarchy — reassign them first.", 409)
    try:
        repo.delete(profile_id)
    except IntegrityError as exc:
        raise DomainError(
            "PROFILE_IN_USE", "This profile is still referenced by other records.", 409) from exc


@handle_errors("list capabilities")
def list_capabilities() -> list[admin_models.CapabilityEntry]:
    return [admin_models.CapabilityEntry(key=k, description=v)
           for k, v in sorted(CAPABILITY_REGISTRY.items())]


@handle_errors("get profile capabilities")
def get_profile_capabilities(profile_id: int) -> admin_models.ProfileCapabilitiesUpdate:
    if get_profile_repository().get(profile_id) is None:
        raise DomainError("PROFILE_NOT_FOUND", f"No profile '{profile_id}'.", 404)
    rows = get_role_capability_repository().list_for_role(profile_id)
    return admin_models.ProfileCapabilitiesUpdate(capability_keys=sorted(r.capability_key for r in rows))


@handle_errors("save profile capabilities")
def save_profile_capabilities(user: CurrentUser, profile_id: int,
                              payload: admin_models.ProfileCapabilitiesUpdate,
                              ) -> admin_models.ProfileCapabilitiesUpdate:
    """Full replace, same shape as crm_service.save_field_permissions(): an
    admin's matrix Save submits the complete desired capability set for one
    profile in a single call."""
    profile = get_profile_repository().get(profile_id)
    if profile is None:
        raise DomainError("PROFILE_NOT_FOUND", f"No profile '{profile_id}'.", 404)
    wanted = set(payload.capability_keys)
    unknown = wanted - set(CAPABILITY_REGISTRY)
    if unknown:
        raise DomainError(
            "CAPABILITY_NOT_ELIGIBLE", f"Unknown capability key(s): {', '.join(sorted(unknown))}.", 422)
    if profile.code == "ADMIN" and wanted != set(CAPABILITY_REGISTRY):
        # Mirrors FLS's own "ADMIN can never be restricted" rule — otherwise
        # an admin could accidentally lock every admin out via this matrix.
        raise DomainError(
            "CANNOT_RESTRICT_ADMIN_PROFILE", "The built-in Admin profile must keep every capability.", 422)

    cap_repo = get_role_capability_repository()
    for existing in cap_repo.list_for_role(profile_id):
        cap_repo.hard_delete(existing.id)
    for key in sorted(wanted):
        cap_repo.create(role_id=profile_id, capability_key=key,
                        created_by=user.employee_id, updated_by=user.employee_id)
    return get_profile_capabilities(profile_id)


# --- Teams -------------------------------------------------------------------
def _team_out(team) -> admin_models.TeamOut:
    return admin_models.TeamOut.model_validate(team)


@handle_errors("list teams")
def list_teams() -> list[admin_models.TeamOut]:
    return [_team_out(t) for t in get_team_repository().list()]


@handle_errors("create team")
def create_team(user: CurrentUser, payload: admin_models.TeamCreate) -> admin_models.TeamOut:
    team = get_team_repository().create(
        display_name=payload.display_name, purpose=payload.purpose, address=payload.address,
        created_by=user.employee_id, updated_by=user.employee_id)
    return _team_out(team)


@handle_errors("update team")
def update_team(user: CurrentUser, team_id: int, payload: admin_models.TeamUpdate) -> admin_models.TeamOut:
    repo = get_team_repository()
    if repo.get(team_id) is None:
        raise DomainError("TEAM_NOT_FOUND", f"No team '{team_id}'.", 404)
    changes = payload.model_dump(exclude_unset=True)
    changes["updated_by"] = user.employee_id
    return _team_out(repo.update(team_id, **changes))


# --- Lookups (generic, by table name) ----------------------------------------
@handle_errors("list lookups")
def list_lookups(table: str) -> list[admin_models.LookupOut]:
    return [admin_models.LookupOut.model_validate(r) for r in _lookup_repo(table).list()]


@handle_errors("add lookup")
def add_lookup(table: str, payload: admin_models.LookupCreate) -> admin_models.LookupOut:
    repo = _lookup_repo(table)
    fields = _lookup_fields(repo, payload)
    if table == _TERRITORY_TABLE:
        _validate_territory_fields(fields, current=None)
    elif not fields.get("code"):
        # Every other lookup table still requires code — Territory is the
        # only one where LookupCreate.code being Optional actually means
        # optional (see admin_models.LookupCreate's docstring).
        raise DomainError("CODE_REQUIRED", "code is required.", 422)
    if fields.get("code"):
        fields["code"] = fields["code"].upper()
    try:
        row = repo.create(**fields)
    except TypeError as exc:
        raise DomainError("LOOKUP_FIELD_INVALID", str(exc), 422) from exc
    return admin_models.LookupOut.model_validate(row)


@handle_errors("update lookup")
def update_lookup(table: str, lookup_id: int,
                  payload: admin_models.LookupUpdate) -> admin_models.LookupOut:
    repo = _lookup_repo(table)
    current = repo.get(lookup_id)
    if current is None:
        raise DomainError("LOOKUP_NOT_FOUND", f"No '{table}' row '{lookup_id}'.", 404)
    fields = _lookup_fields(repo, payload)
    if table == _TERRITORY_TABLE:
        _validate_territory_fields(fields, current=current, territory_id=lookup_id)
    row = repo.update(lookup_id, **fields)
    return admin_models.LookupOut.model_validate(row)


@handle_errors("delete lookup")
def delete_lookup(table: str, lookup_id: int) -> None:
    repo = _lookup_repo(table)
    if repo.get(lookup_id) is None:
        raise DomainError("LOOKUP_NOT_FOUND", f"No '{table}' row '{lookup_id}'.", 404)
    try:
        repo.delete(lookup_id)
    except IntegrityError as exc:
        raise DomainError(
            "LOOKUP_IN_USE", f"'{table}' row '{lookup_id}' is still referenced by other rows.",
            409) from exc
