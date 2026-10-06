"""CRM module business logic (§1/§6 of the API spec) — Accounts, Contacts,
Account assignments, Opportunities, Opportunity documents. All IMPLEMENTED.

Rules enforced:
- account create  : new accounts always start as PROSPECT; first_contact_at stamped.
- account promote : PROSPECT -> CLIENT only, and only with >= 1 SIGNED SOW agreement.
- account delete  : soft-delete blocked while the account has active agreements/projects.
- scope (lead, account, contact, opportunity, campaign): ownership + Role
  Hierarchy + OWD + user-based record sharing + records.see_all — see
  services/record_access_service.py, the centralized decision point, and
  _in_read_scope()/_in_write_scope()/_in_delete_scope() below, which delegate
  to it. (Agreement/Project/SOW/Communications use src/utils/scope.py, which
  has always been Role-Hierarchy-inclusive and is untouched by this file.)
- contact           : at most one is_primary contact per account.
- account_assignment: exactly one of employee_id/team_id (also enforced by a
  DB check constraint — see models/crm_models.py).

Depends only on repository classes (see src/repositories/) — never on a
SQLAlchemy Session directly. Swapping to a different repository
implementation requires zero changes here.
"""
import json
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from src.config.config_reader import get_settings
from src.models import crm_models
from src.models.common import Page
from src.models.crm_models import (
    Account, Campaign, CadenceStep, CadenceTemplate, Contact, Lead, Opportunity, Signal,
)
from src.models.enums import (
    AccountType,
    CadenceStepType,
    CadenceTaskStatus,
    LeadCadenceEnrollmentStatus,
    LeadCommunicationChannel,
    LeadScoringOperator,
    LeadStatus,
    OpportunityStage,
    OrgWideDefaultAccessLevel,
    RecordAccessLevel,
    SignalType,
)
from src.repositories._base import resolve_lookup_id
from src.repositories.activity_repository import CommunicationRepository, NotificationRepository
from src.repositories.admin_repository import (
    EmployeeRepository, get_profile_repository, get_territory_repository,
)
from src.repositories.contracts_repository import AgreementRepository
from src.repositories.crm_repository import (
    AccountAssignmentRepository,
    AccountRepository,
    CadenceStepRepository,
    CadenceTaskRepository,
    CadenceTemplateRepository,
    CampaignRepository,
    ContactRepository,
    FieldPermissionRepository,
    LeadCadenceEnrollmentRepository,
    LeadRepository,
    LeadScoringRuleRepository,
    OpportunityDocumentRepository,
    OpportunityRepository,
    OrgWideDefaultRepository,
    ProductRepository,
    RecordShareRepository,
    SignalRepository,
    get_account_type_repository,
    get_contact_type_repository,
    get_field_permission_repository,
    get_opportunity_stage_repository,
    get_org_wide_default_repository,
    get_record_share_repository,
)
from src.repositories.delivery_repository import AssetRepository
from src.repositories.project_repository import ProjectRepository
from src.services import record_access_service
from src.services.admin_service import verified_employee_uuid
from src.services.email_client import EmailSender
from src.services.inbound_email_client import InboundEmailReceiver
from src.services.llm_client import LLMClient
from src.utils import geo
from src.utils.error_handling import handle_errors
from src.utils.exceptions import DomainError
from src.utils.permissions import CAPABILITY_REGISTRY
from src.utils.security import CurrentUser


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sees_all(user: CurrentUser) -> bool:
    return user.has_capability("records.see_all")


def _owned_by(user: CurrentUser, row: Account | Opportunity | Lead) -> bool:
    """CurrentUser.employee_id is a gateway-forwarded identity string; in a
    real deployment it's the employee's DB id (a UUID). Anything that isn't a
    parseable UUID (e.g. the DEV_AUTH_BYPASS "dev-admin" placeholder) simply
    never matches an owner — that's fine since bypass always grants ADMIN,
    which already sees everything via _sees_all()."""
    if row.owner_employee_id is None:
        return False
    try:
        return row.owner_employee_id == UUID(user.employee_id)
    except ValueError:
        return False


def _hierarchy_scope(user: CurrentUser, row: Account | Opportunity | Lead) -> bool:
    """records.see_all, ownership, or a role-hierarchy subordinate owns it —
    this is the pre-OWD scope rule verbatim (what PRIVATE reproduces), and is
    also the WRITE-side fallback for every OWD access level (OWD only ever
    widens READ beyond this; see _in_write_scope()).

    NOTE: hierarchy visibility (CurrentUser.subordinate_employee_ids())
    belongs here, and ONLY here — never inside _owned_by(). list_my_cadence_
    tasks() calls _owned_by() directly because "my tasks" must mean
    literally-mine; folding hierarchy into _owned_by() would leak a
    manager's reports' tasks into their own "my tasks" view."""
    if _sees_all(user) or _owned_by(user, row):
        return True
    return row.owner_employee_id is not None and row.owner_employee_id in user.subordinate_employee_ids()


#: Any row this module's OWD/sharing scope rule applies to. Deliberately
#: NOT Agreement/Project/SOW/Communications — those keep using
#: src/utils/scope.py's owned_account_ids()/require_account_scope()/
#: require_lead_scope(), which still consult Role Hierarchy exactly as
#: before (see record_access_service.py's module docstring for why this
#: split is deliberate, not an oversight).
_ScopedRow = Account | Opportunity | Lead | Contact | Campaign


def _object_name_for(row: _ScopedRow) -> str:
    if isinstance(row, Account):
        return "ACCOUNT"
    if isinstance(row, Opportunity):
        return "OPPORTUNITY"
    if isinstance(row, Contact):
        return "CONTACT"
    if isinstance(row, Campaign):
        return "CAMPAIGN"
    return "LEAD"


# --- record-level access: Ownership + Role Hierarchy + OWD + Sharing -------
# _in_read_scope()/_in_write_scope()/_require_read_scope()/_require_write_scope()
# delegate entirely to services/record_access_service.py, the single
# centralized place this decision is made for LEAD/ACCOUNT/CONTACT/
# OPPORTUNITY/CAMPAIGN — see that module's docstring for the exact
# precedence (owner -> Role Hierarchy -> OWD -> Sharing) and for why
# Territory is deliberately NOT part of it. _hierarchy_scope() above is a
# separate, narrower helper: still used only by list_my_cadence_tasks()'s
# literal-"my tasks" carve-out (which must exclude subordinates' tasks) and
# by nothing in this scope block. Same call signatures as before this
# feature, so no call site elsewhere in this file needed to change.
def _in_read_scope(user: CurrentUser, row: _ScopedRow, owd_repo: OrgWideDefaultRepository) -> bool:
    return record_access_service.can_user_access_record(
        user, _object_name_for(row), row, RecordAccessLevel.READ,
        share_repo=get_record_share_repository(), owd_repo=owd_repo)


def _in_write_scope(user: CurrentUser, row: _ScopedRow, owd_repo: OrgWideDefaultRepository) -> bool:
    return record_access_service.can_user_access_record(
        user, _object_name_for(row), row, RecordAccessLevel.EDIT,
        share_repo=get_record_share_repository(), owd_repo=owd_repo)


def _in_delete_scope(user: CurrentUser, row: _ScopedRow, owd_repo: OrgWideDefaultRepository) -> bool:
    """DELETE is never satisfiable via OWD or sharing (see
    record_access_service.can_user_access_record()) — only records.see_all
    or direct ownership, layered underneath the object's own existing delete
    capability (leads.delete/accounts.delete/... — checked separately at the
    route layer via requires())."""
    return record_access_service.can_user_access_record(
        user, _object_name_for(row), row, RecordAccessLevel.DELETE,
        share_repo=get_record_share_repository(), owd_repo=owd_repo)


def _require_read_scope(user: CurrentUser, row: _ScopedRow,
                        message: str = "Account is outside your data scope.") -> None:
    if not _in_read_scope(user, row, get_org_wide_default_repository()):
        raise DomainError("FORBIDDEN", message, 403)


def _require_write_scope(user: CurrentUser, row: _ScopedRow,
                         message: str = "Account is outside your data scope.") -> None:
    if not _in_write_scope(user, row, get_org_wide_default_repository()):
        raise DomainError("FORBIDDEN", message, 403)


def _require_delete_scope(user: CurrentUser, row: _ScopedRow,
                          message: str = "Account is outside your data scope.") -> None:
    if not _in_delete_scope(user, row, get_org_wide_default_repository()):
        raise DomainError("FORBIDDEN", message, 403)


def _permission_flags(user: CurrentUser, row: _ScopedRow) -> tuple[bool, bool]:
    """(can_edit, can_delete) for one row — what every *Out schema for these
    5 objects now carries, computed once here so list/get/create/update
    responses all agree and no logic is duplicated per call site."""
    owd_repo = get_org_wide_default_repository()
    share_repo = get_record_share_repository()
    object_name = _object_name_for(row)
    return record_access_service.compute_permissions(
        user, object_name, row, share_repo=share_repo, owd_repo=owd_repo)


def _get_or_404(repo: AccountRepository, cid: str) -> Account:
    row = repo.get(cid)
    if row is None:
        raise DomainError("ACCOUNT_NOT_FOUND", f"No account '{cid}'.", 404)
    return row


def _type_id(code: str) -> int:
    """Resolve an account_type lookup code (see models.enums.AccountType) to
    its DB row id. The four codes are seeded by an Alembic migration —
    reference/lookup data, not mock business data. Kept as its own function
    (rather than a bare resolve_lookup_id() call) because a missing
    account_type is a 500 seeding problem, not a 422 bad-input one."""
    return resolve_lookup_id(
        get_account_type_repository(), code, "ACCOUNT_TYPE_NOT_SEEDED", "account_type",
        status_code=500, message=f"account_type '{code}' is missing — run `alembic upgrade head`.",
    )


def _account_type_map() -> dict[int, str]:
    """{account_type.id: code}, built once per call site rather than once
    per row — account_type is a handful of seeded rows, but resolving it via
    a fresh repository round-trip for every row in a list is still an N+1."""
    return {t.id: t.code for t in get_account_type_repository().list()}


def _territory_map() -> dict[int, str]:
    """{territory.id: display_name} — resolved by id, displayed by Name,
    never Code (which is optional and can be null); same one-round-trip-
    per-call-site reasoning as _account_type_map(). Shared by both Account
    and Lead output builders."""
    return {t.id: t.display_name for t in get_territory_repository().list()}


def _territory_code(territory_id: int | None, territory_map: dict[int, str]) -> str | None:
    """None-safe dict lookup — territory_id (unlike account_type_id) is
    nullable (a row created before this feature, or with no owner to
    default from, simply has none). Despite the name (kept to minimize the
    diff at every call site), this now returns the territory's display_name,
    not its code — see _territory_map()."""
    return territory_map.get(territory_id) if territory_id is not None else None


def _owner_territory_id(employees: EmployeeRepository, owner_employee_id) -> int | None:
    """The Sales Territory/Region an Account/Lead defaults to at create time
    — its resolved owner's Employee.territory_id, or None if there's no
    owner (nothing to default from) or that owner has no territory set.
    Never re-derived afterward (see Account.territory_id's docstring) —
    call only from create_account()/create_lead()."""
    if owner_employee_id is None:
        return None
    owner = employees.get(owner_employee_id)
    return owner.territory_id if owner is not None else None


def _out(row: Account, type_map: dict[int, str] | None = None,
        user: CurrentUser | None = None, territory_map: dict[int, str] | None = None) -> crm_models.AccountOut:
    # row.account_type is a lazy relationship on an object whose session has
    # already closed — resolve the code via a lookup map instead of touching
    # the relationship (which would raise DetachedInstanceError).
    codes = type_map if type_map is not None else _account_type_map()
    territories = territory_map if territory_map is not None else _territory_map()
    can_edit, can_delete = _permission_flags(user, row) if user is not None else (True, True)
    return crm_models.AccountOut(
        id=row.id, legal_name=row.legal_name, account_type=codes[row.account_type_id],
        account_site=row.account_site, industry=row.industry, website=row.website, phone=row.phone,
        address=row.address, shipping_address=row.shipping_address,
        billing_country=row.billing_country, billing_state_province=row.billing_state_province,
        region=geo.derive_region(row.billing_country, row.billing_state_province),
        shipping_country=row.shipping_country, shipping_state_province=row.shipping_state_province,
        billing_city=row.billing_city, billing_postal_code=row.billing_postal_code,
        shipping_city=row.shipping_city, shipping_postal_code=row.shipping_postal_code,
        annual_revenue=row.annual_revenue, num_employees=row.num_employees,
        ownership=row.ownership, ticker_symbol=row.ticker_symbol, rating=row.rating,
        account_number=row.account_number, sic_code=row.sic_code, description=row.description,
        parent_account_id=row.parent_account_id,
        owner_employee_id=row.owner_employee_id,
        territory=_territory_code(row.territory_id, territories),
        first_contact_at=row.first_contact_at,
        promoted_to_client_at=row.promoted_to_client_at,
        can_edit=can_edit, can_delete=can_delete,
        created_at=row.created_at, updated_at=row.updated_at,
        created_by=row.created_by, updated_by=row.updated_by,
    )


# --- public API (called by server routes; repos injected via FastAPI Depends) -----
@handle_errors("list accounts")
def list_accounts(
    user: CurrentUser, repo: AccountRepository, *,
    q: str | None = None, account_type: str | None = None,
    page: int = 1, page_size: int = 20,
) -> Page[crm_models.AccountOut]:
    type_map = _account_type_map()
    owd_repo = get_org_wide_default_repository()
    rows = [r for r in repo.list() if _in_read_scope(user, r, owd_repo)]
    if q:
        needle = q.lower()
        rows = [r for r in rows if needle in r.legal_name.lower()]
    if account_type:
        want = account_type.upper()
        rows = [r for r in rows if type_map.get(r.account_type_id) == want]
    rows.sort(key=lambda r: r.id)
    total = len(rows)
    start = (page - 1) * page_size
    window = rows[start:start + page_size]
    fls = get_effective_field_permissions(user, get_field_permission_repository(), "ACCOUNT")
    territory_map = _territory_map()
    items = [_redact(_out(r, type_map, user, territory_map), fls) for r in window]
    return Page(items=items, total=total, page=page, page_size=page_size)


@handle_errors("get account")
def get_account(user: CurrentUser, repo: AccountRepository, cid: str) -> crm_models.AccountOut:
    row = _get_or_404(repo, cid)
    _require_read_scope(user, row)
    fls = get_effective_field_permissions(user, get_field_permission_repository(), "ACCOUNT")
    return _redact(_out(row, user=user), fls)


def _validate_owner(employees: EmployeeRepository, owner_employee_id) -> None:
    """The account.owner_employee_id FK points at employee.id. Validate it up
    front so an unknown employee returns a clean 400 instead of the raw
    ForeignKeyViolation surfacing as a 500. Null is allowed (owner optional)."""
    if owner_employee_id is None:
        return
    if employees.get(owner_employee_id) is None:
        raise DomainError(
            "UNKNOWN_EMPLOYEE",
            f"owner_employee_id {owner_employee_id} does not match any employee.",
            400)


#: Shipping defaults to Billing — Country + State/Province + Street + City +
#: Postal Code as one unit, not just the street — whenever Shipping is empty
#: (an account with no Billing address to copy leaves Shipping empty too, and
#: an already-set Shipping street/city/postal code, whether persisted or
#: supplied on this same call, is never overwritten). Shared by
#: create_account()/update_account() so the rule can't drift between the two.
#: Each argument is (country, state_province, street, city, postal_code).
def _billing_to_shipping_defaults(
    billing: tuple[str | None, str | None, str | None, str | None, str | None],
    shipping: tuple[str | None, str | None, str | None, str | None, str | None],
) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    billing_has_address = any(billing[2:])
    shipping_has_address = any(shipping[2:])
    if shipping_has_address or not billing_has_address:
        return shipping
    return billing


@handle_errors("create account")
def create_account(
    user: CurrentUser, repo: AccountRepository,
    employees: EmployeeRepository,
    payload: crm_models.AccountCreate,
) -> crm_models.AccountOut:
    _validate_owner(employees, payload.owner_employee_id)
    geo.validate_country_state_province(payload.billing_country, payload.billing_state_province)
    geo.validate_country_state_province(payload.shipping_country, payload.shipping_state_province)
    (shipping_country, shipping_state_province, shipping_address,
     shipping_city, shipping_postal_code) = _billing_to_shipping_defaults(
        (payload.billing_country, payload.billing_state_province, payload.address,
         payload.billing_city, payload.billing_postal_code),
        (payload.shipping_country, payload.shipping_state_province, payload.shipping_address,
         payload.shipping_city, payload.shipping_postal_code),
    )
    # See create_lead()'s identical comment: a rep creating an account with
    # no explicit owner becomes its owner, so it isn't immediately outside
    # their own scope.
    owner_employee_id = payload.owner_employee_id or verified_employee_uuid(user)
    # Sales Territory/Region defaults from the resolved owner's own
    # assignment (see Account.territory_id's docstring) — not from the
    # acting user, so an ADMIN/AE creating an account on behalf of a
    # different-territory rep still gets that rep's territory, not their own.
    territory_id = _owner_territory_id(employees, owner_employee_id)
    now = _now()
    new_id = repo.next_id()
    # FLS applies to create too, same as get/update/list — see create_lead()'s
    # identical comment. legal_name is excluded: required at the DB/create
    # level regardless of FLS editability.
    fls = get_effective_field_permissions(user, get_field_permission_repository(), "ACCOUNT")
    changes = _drop_noneditable({
        "account_site": payload.account_site, "industry": payload.industry,
        "website": payload.website, "phone": payload.phone, "address": payload.address,
        "shipping_address": shipping_address,
        "billing_country": payload.billing_country, "billing_state_province": payload.billing_state_province,
        "shipping_country": shipping_country, "shipping_state_province": shipping_state_province,
        "billing_city": payload.billing_city, "billing_postal_code": payload.billing_postal_code,
        "shipping_city": shipping_city, "shipping_postal_code": shipping_postal_code,
        "annual_revenue": payload.annual_revenue,
        "num_employees": payload.num_employees, "ownership": payload.ownership,
        "ticker_symbol": payload.ticker_symbol, "rating": payload.rating,
        "account_number": payload.account_number, "sic_code": payload.sic_code,
        "description": payload.description, "parent_account_id": payload.parent_account_id,
    }, fls)
    row = repo.create(
        id=new_id,
        legal_name=payload.legal_name.strip(),
        account_type_id=_type_id(AccountType.PROSPECT.value),   # rule: always PROSPECT
        **changes,
        owner_employee_id=owner_employee_id,
        territory_id=territory_id,
        first_contact_at=now,
        promoted_to_client_at=None,
        created_by=user.employee_id,
        updated_by=user.employee_id,
    )
    return _redact(_out(row), fls)


@handle_errors("update account")
def update_account(
    user: CurrentUser, repo: AccountRepository, employees: EmployeeRepository,
    cid: str, payload: crm_models.AccountUpdate,
) -> crm_models.AccountOut:
    row = _get_or_404(repo, cid)
    _require_write_scope(user, row)
    fls = get_effective_field_permissions(user, get_field_permission_repository(), "ACCOUNT")
    changes = _drop_noneditable(payload.model_dump(exclude_unset=True), fls)
    if "owner_employee_id" in changes:
        _validate_owner(employees, changes["owner_employee_id"])
    # Validate against the resulting pair (changed half + whichever half of
    # billing/shipping isn't part of this patch), same reasoning as
    # update_lead()'s identical check — a partial patch that only touches
    # one of country/state_province must still resolve to a valid pair.
    if "billing_country" in changes or "billing_state_province" in changes:
        geo.validate_country_state_province(
            changes.get("billing_country", row.billing_country),
            changes.get("billing_state_province", row.billing_state_province),
        )
    if "shipping_country" in changes or "shipping_state_province" in changes:
        geo.validate_country_state_province(
            changes.get("shipping_country", row.shipping_country),
            changes.get("shipping_state_province", row.shipping_state_province),
        )
    # Same Billing -> Shipping default as create_account(), re-applied
    # against the resulting (patched-or-existing) values so it still fires
    # when e.g. Billing Address is added on a patch that leaves Shipping
    # untouched — see _billing_to_shipping_defaults()'s docstring.
    (changes["shipping_country"], changes["shipping_state_province"], changes["shipping_address"],
     changes["shipping_city"], changes["shipping_postal_code"]) = _billing_to_shipping_defaults(
        (
            changes.get("billing_country", row.billing_country),
            changes.get("billing_state_province", row.billing_state_province),
            changes.get("address", row.address),
            changes.get("billing_city", row.billing_city),
            changes.get("billing_postal_code", row.billing_postal_code),
        ),
        (
            changes.get("shipping_country", row.shipping_country),
            changes.get("shipping_state_province", row.shipping_state_province),
            changes.get("shipping_address", row.shipping_address),
            changes.get("shipping_city", row.shipping_city),
            changes.get("shipping_postal_code", row.shipping_postal_code),
        ),
    )
    changes["updated_by"] = user.employee_id
    updated = repo.update(cid, **changes)
    return _redact(_out(updated), fls)


@handle_errors("delete account")
def delete_account(
    user: CurrentUser, repo: AccountRepository,
    agreements: AgreementRepository, projects: ProjectRepository, cid: str,
) -> None:
    row = _get_or_404(repo, cid)
    _require_delete_scope(user, row)
    active_agreements = agreements.count_active_for_account(cid)
    active_projects = projects.count_active_for_account(cid)
    if active_agreements or active_projects:
        raise DomainError(
            "ACCOUNT_HAS_DEPENDENTS",
            f"Cannot delete: {active_agreements} active agreement(s) and "
            f"{active_projects} active project(s) exist.", 409)
    repo.update(cid, updated_by=user.employee_id)  # stamp who deleted it, for audit
    repo.delete(cid)


@handle_errors("promote account")
def promote_account(
    user: CurrentUser, repo: AccountRepository,
    agreements: AgreementRepository, cid: str,
) -> crm_models.AccountOut:
    row = _get_or_404(repo, cid)
    _require_write_scope(user, row)
    current_code = get_account_type_repository().get(row.account_type_id).code
    if current_code == AccountType.CLIENT.value:
        raise DomainError("ALREADY_CLIENT", "Account is already a CLIENT.", 409)
    if not agreements.has_signed_sow(cid):
        raise DomainError(
            "PROMOTE_REQUIRES_SIGNED_SOW",
            "Promotion to CLIENT requires at least one SIGNED SOW.", 422)
    updated = repo.update(
        cid,
        account_type_id=_type_id(AccountType.CLIENT.value),
        promoted_to_client_at=_now(),
        updated_by=user.employee_id,
    )
    return _out(updated)


# --- Contacts -----------------------------------------------------------------
def _contact_type_id(code: str) -> int:
    return resolve_lookup_id(get_contact_type_repository(), code, "CONTACT_TYPE_NOT_FOUND", "contact_type")


def _contact_out(row, type_map: dict[int, str] | None = None,
                 user: CurrentUser | None = None) -> crm_models.ContactOut:
    codes = type_map if type_map is not None else {
        t.id: t.code for t in get_contact_type_repository().list()}
    ctype = codes[row.contact_type_id]
    can_edit, can_delete = _permission_flags(user, row) if user is not None else (True, True)
    return crm_models.ContactOut(
        id=row.id, account_id=row.account_id, contact_type=ctype,
        salutation=row.salutation, full_name=row.full_name, title=row.title,
        department=row.department, birthdate=row.birthdate,
        email=row.email, phone=row.phone, mobile_phone=row.mobile_phone,
        home_phone=row.home_phone, other_phone=row.other_phone,
        assistant_name=row.assistant_name, assistant_phone=row.assistant_phone,
        lead_source=row.lead_source, address=row.address, other_address=row.other_address,
        description=row.description, reports_to_contact_id=row.reports_to_contact_id,
        is_primary=row.is_primary, is_distribution_list=row.is_distribution_list,
        can_edit=can_edit, can_delete=can_delete,
        created_at=row.created_at, updated_at=row.updated_at,
        created_by=row.created_by, updated_by=row.updated_by,
    )


@handle_errors("list contacts")
def list_contacts(user: CurrentUser, account_repo: AccountRepository, contact_repo: ContactRepository,
                  cid: str) -> list[crm_models.ContactOut]:
    """Listing an account's contacts still requires READ on the ACCOUNT
    itself (structural — you can't ask for "this account's contacts"
    without being able to see the account), but which contacts actually
    come back is independently filtered by CONTACT's own OWD/ownership/
    sharing (see record_access_service.py) — CONTACT can be configured more
    restrictively than ACCOUNT (e.g. Account PUBLIC_READ_ONLY, Contact
    PRIVATE, to keep contact PII tighter than the account shell)."""
    account = _get_or_404(account_repo, cid)
    _require_read_scope(user, account)
    owd_repo = get_org_wide_default_repository()
    type_map = {t.id: t.code for t in get_contact_type_repository().list()}
    contacts = [c for c in contact_repo.list_for_account(cid) if _in_read_scope(user, c, owd_repo)]
    return [_contact_out(c, type_map, user) for c in contacts]


@handle_errors("add contact")
def add_contact(user: CurrentUser, account_repo: AccountRepository,
                contact_repo: ContactRepository, cid: str,
                payload: crm_models.ContactCreate) -> crm_models.ContactOut:
    account = _get_or_404(account_repo, cid)
    _require_write_scope(user, account)
    if payload.is_primary:
        for existing in contact_repo.list_for_account(cid):
            if existing.is_primary:
                contact_repo.update(existing.id, is_primary=False, updated_by=user.employee_id)
    row = contact_repo.create(
        account_id=cid, contact_type_id=_contact_type_id(payload.contact_type),
        salutation=payload.salutation, full_name=payload.full_name, title=payload.title,
        department=payload.department, birthdate=payload.birthdate,
        email=payload.email, phone=payload.phone, mobile_phone=payload.mobile_phone,
        home_phone=payload.home_phone, other_phone=payload.other_phone,
        assistant_name=payload.assistant_name, assistant_phone=payload.assistant_phone,
        lead_source=payload.lead_source, address=payload.address, other_address=payload.other_address,
        description=payload.description, reports_to_contact_id=payload.reports_to_contact_id,
        is_primary=payload.is_primary, is_distribution_list=payload.is_distribution_list,
        created_by=user.employee_id, updated_by=user.employee_id,
    )
    return _contact_out(row)


@handle_errors("update contact")
def update_contact(user: CurrentUser, account_repo: AccountRepository, contact_repo: ContactRepository,
                   contact_id: UUID, payload: crm_models.ContactUpdate) -> crm_models.ContactOut:
    row = contact_repo.get(contact_id)
    if row is None:
        raise DomainError("CONTACT_NOT_FOUND", f"No contact '{contact_id}'.", 404)
    # CONTACT-level check (its own OWD/sharing; ownership derived from the
    # parent Account — see record_access_service.effective_owner_employee_id),
    # not the parent Account's own scope.
    _require_write_scope(user, row, "Contact is outside your data scope.")
    changes = payload.model_dump(exclude_unset=True)
    if "contact_type" in changes:
        changes["contact_type_id"] = _contact_type_id(changes.pop("contact_type"))
    if changes.get("is_primary"):
        for other in contact_repo.list_for_account(row.account_id):
            if other.id != contact_id and other.is_primary:
                contact_repo.update(other.id, is_primary=False, updated_by=user.employee_id)
    changes["updated_by"] = user.employee_id
    updated = contact_repo.update(contact_id, **changes)
    return _contact_out(updated, user=user)


@handle_errors("delete contact")
def delete_contact(user: CurrentUser, account_repo: AccountRepository, contact_repo: ContactRepository,
                   contact_id: UUID) -> None:
    row = contact_repo.get(contact_id)
    if row is None:
        raise DomainError("CONTACT_NOT_FOUND", f"No contact '{contact_id}'.", 404)
    _require_delete_scope(user, row, "Contact is outside your data scope.")
    contact_repo.update(contact_id, updated_by=user.employee_id)
    contact_repo.delete(contact_id)


# --- Account assignments ------------------------------------------------------
def _role_id(code: str) -> int:
    return resolve_lookup_id(get_profile_repository(), code, "ROLE_NOT_FOUND", "role code")


def _assignment_out(row, role_map: dict[int, str] | None = None) -> crm_models.AccountAssignmentOut:
    codes = role_map if role_map is not None else {r.id: r.code for r in get_profile_repository().list()}
    return crm_models.AccountAssignmentOut(
        id=row.id, account_id=row.account_id, employee_id=row.employee_id,
        team_id=row.team_id, role=codes[row.role_id], assigned_from=row.assigned_from,
        assigned_until=row.assigned_until,
        created_at=row.created_at, updated_at=row.updated_at,
        created_by=row.created_by, updated_by=row.updated_by,
    )


@handle_errors("list assignments")
def list_assignments(user: CurrentUser, account_repo: AccountRepository,
                     assignment_repo: AccountAssignmentRepository,
                     cid: str) -> list[crm_models.AccountAssignmentOut]:
    account = _get_or_404(account_repo, cid)
    _require_read_scope(user, account)
    role_map = {r.id: r.code for r in get_profile_repository().list()}
    return [_assignment_out(a, role_map) for a in assignment_repo.list_for_account(cid)]


@handle_errors("add assignment")
def add_assignment(user: CurrentUser, account_repo: AccountRepository,
                   assignment_repo: AccountAssignmentRepository, cid: str,
                   payload: crm_models.AccountAssignmentCreate) -> crm_models.AccountAssignmentOut:
    account = _get_or_404(account_repo, cid)
    _require_write_scope(user, account)
    if (payload.employee_id is None) == (payload.team_id is None):
        raise DomainError("ASSIGNMENT_TARGET_INVALID",
                          "Exactly one of employee_id or team_id must be set.", 422)
    row = assignment_repo.create(
        account_id=cid, employee_id=payload.employee_id, team_id=payload.team_id,
        role_id=_role_id(payload.role), assigned_from=payload.assigned_from,
        assigned_until=payload.assigned_until,
        created_by=user.employee_id, updated_by=user.employee_id,
    )
    return _assignment_out(row)


@handle_errors("update assignment")
def update_assignment(user: CurrentUser, account_repo: AccountRepository,
                      assignment_repo: AccountAssignmentRepository,
                      assignment_id: UUID,
                      payload: crm_models.AccountAssignmentUpdate) -> crm_models.AccountAssignmentOut:
    row = assignment_repo.get(assignment_id)
    if row is None:
        raise DomainError("ASSIGNMENT_NOT_FOUND", f"No assignment '{assignment_id}'.", 404)
    _require_write_scope(user, _get_or_404(account_repo, row.account_id))
    changes = payload.model_dump(exclude_unset=True)
    if "role" in changes:
        changes["role_id"] = _role_id(changes.pop("role"))
    changes["updated_by"] = user.employee_id
    updated = assignment_repo.update(assignment_id, **changes)
    return _assignment_out(updated)


# --- Opportunities --------------------------------------------------------------
def _stage_id(code: str) -> int:
    return resolve_lookup_id(get_opportunity_stage_repository(), code, "OPPORTUNITY_STAGE_NOT_FOUND", "stage")


def _opportunity_out(row: Opportunity, stage_map: dict[int, str] | None = None,
                     user: CurrentUser | None = None) -> crm_models.OpportunityOut:
    codes = stage_map if stage_map is not None else {
        s.id: s.code for s in get_opportunity_stage_repository().list()}
    can_edit, can_delete = _permission_flags(user, row) if user is not None else (True, True)
    return crm_models.OpportunityOut(
        id=row.id, account_id=row.account_id, name=row.name, stage=codes[row.opportunity_stage_id],
        estimated_value=row.estimated_value, currency=row.currency,
        expected_close_date=row.expected_close_date, owner_employee_id=row.owner_employee_id,
        lost_reason=row.lost_reason, probability_percent=row.probability_percent,
        opportunity_type=row.opportunity_type, next_step=row.next_step, description=row.description,
        lead_id=row.lead_id, campaign_id=row.campaign_id,
        originating_asset_id=row.originating_asset_id,
        can_edit=can_edit, can_delete=can_delete,
        created_at=row.created_at, updated_at=row.updated_at,
        created_by=row.created_by, updated_by=row.updated_by,
    )


@handle_errors("list opportunities")
def list_opportunities(user: CurrentUser,
                       opportunity_repo: OpportunityRepository) -> list[crm_models.OpportunityOut]:
    stage_map = {s.id: s.code for s in get_opportunity_stage_repository().list()}
    owd_repo = get_org_wide_default_repository()
    rows = [r for r in opportunity_repo.list() if _in_read_scope(user, r, owd_repo)]
    rows.sort(key=lambda r: r.id)
    fls = get_effective_field_permissions(user, get_field_permission_repository(), "OPPORTUNITY")
    return [_redact(_opportunity_out(r, stage_map, user), fls) for r in rows]


@handle_errors("get opportunity")
def get_opportunity(user: CurrentUser, opportunity_repo: OpportunityRepository,
                    oid: str) -> crm_models.OpportunityOut:
    row = opportunity_repo.get(oid)
    if row is None:
        raise DomainError("OPPORTUNITY_NOT_FOUND", f"No opportunity '{oid}'.", 404)
    _require_read_scope(user, row)
    fls = get_effective_field_permissions(user, get_field_permission_repository(), "OPPORTUNITY")
    return _redact(_opportunity_out(row, user=user), fls)


@handle_errors("create opportunity")
def create_opportunity(user: CurrentUser, account_repo: AccountRepository,
                       opportunity_repo: OpportunityRepository,
                       payload: crm_models.OpportunityCreate,
                       asset_repo: AssetRepository | None = None) -> crm_models.OpportunityOut:
    """asset_repo is optional so every existing caller (including
    convert_lead()) keeps working unchanged; it's only required to close the
    renewal loop when payload.originating_asset_id is actually set — the
    route always passes it (see crm_routes.py)."""
    _get_or_404(account_repo, payload.account_id)
    asset = None
    if payload.originating_asset_id is not None:
        if asset_repo is None:
            raise DomainError(
                "ASSET_REPOSITORY_UNAVAILABLE",
                "originating_asset_id was supplied but this deployment cannot resolve assets.", 500)
        asset = asset_repo.get(payload.originating_asset_id)
        if asset is None:
            raise DomainError(
                "ASSET_NOT_FOUND", f"No asset '{payload.originating_asset_id}'.", 404)
    # See create_lead()'s identical comment: a rep creating an opportunity
    # with no explicit owner becomes its owner. convert_lead() always passes
    # one explicitly (the converting lead's own owner), so this default only
    # ever kicks in for a direct POST /opportunities call.
    owner_employee_id = payload.owner_employee_id or verified_employee_uuid(user)
    new_id = opportunity_repo.next_id()
    # FLS applies to create too, same as get/update/list — see create_lead()'s
    # identical comment. name is excluded: required at the DB/create level
    # regardless of FLS editability.
    fls = get_effective_field_permissions(user, get_field_permission_repository(), "OPPORTUNITY")
    changes = _drop_noneditable({
        "estimated_value": payload.estimated_value, "currency": payload.currency,
        "expected_close_date": payload.expected_close_date,
        "probability_percent": payload.probability_percent, "opportunity_type": payload.opportunity_type,
        "next_step": payload.next_step, "description": payload.description,
    }, fls)
    row = opportunity_repo.create(
        id=new_id, account_id=payload.account_id, name=payload.name,
        opportunity_stage_id=_stage_id(OpportunityStage.NEW.value),
        owner_employee_id=owner_employee_id,
        **changes,
        # A renewal/cross-sell Opportunity inherits the campaign that produced
        # the Asset it's renewing — this is the ERD's dashed "renewal" arrow,
        # made real: the next deal is attributed to where the business
        # actually came from, not treated as a brand-new, unattributed one.
        campaign_id=asset.campaign_id if asset is not None else None,
        originating_asset_id=payload.originating_asset_id,
        created_by=user.employee_id, updated_by=user.employee_id,
    )
    if asset is not None:
        asset_repo.update(asset.id, renewed_by_opportunity_id=row.id, updated_by=user.employee_id)
    return _redact(_opportunity_out(row), fls)


@handle_errors("update opportunity")
def update_opportunity(user: CurrentUser, opportunity_repo: OpportunityRepository, oid: str,
                       payload: crm_models.OpportunityUpdate) -> crm_models.OpportunityOut:
    row = opportunity_repo.get(oid)
    if row is None:
        raise DomainError("OPPORTUNITY_NOT_FOUND", f"No opportunity '{oid}'.", 404)
    _require_write_scope(user, row)
    fls = get_effective_field_permissions(user, get_field_permission_repository(), "OPPORTUNITY")
    changes = _drop_noneditable(payload.model_dump(exclude_unset=True), fls)
    if "stage" in changes:
        changes["opportunity_stage_id"] = _stage_id(changes.pop("stage"))
    changes["updated_by"] = user.employee_id
    updated = opportunity_repo.update(oid, **changes)
    return _redact(_opportunity_out(updated, user=user), fls)


@handle_errors("delete opportunity")
def delete_opportunity(user: CurrentUser, opportunity_repo: OpportunityRepository, oid: str) -> None:
    row = opportunity_repo.get(oid)
    if row is None:
        raise DomainError("OPPORTUNITY_NOT_FOUND", f"No opportunity '{oid}'.", 404)
    _require_delete_scope(user, row)
    opportunity_repo.update(oid, updated_by=user.employee_id)
    opportunity_repo.delete(oid)


# --- Opportunity documents -------------------------------------------------------
def _opportunity_document_out(row) -> crm_models.OpportunityDocumentOut:
    return crm_models.OpportunityDocumentOut(
        id=row.id, opportunity_id=row.opportunity_id, version_number=row.version_number,
        doc_type=row.doc_type, status=row.status, sharepoint_item_id=row.sharepoint_item_id,
        sharepoint_url=row.sharepoint_url, filename=row.filename, uploaded_at=row.uploaded_at,
        created_at=row.created_at, updated_at=row.updated_at,
        created_by=row.created_by, updated_by=row.updated_by,
    )


def _get_opportunity_or_404(opportunity_repo: OpportunityRepository, oid: str) -> Opportunity:
    row = opportunity_repo.get(oid)
    if row is None:
        raise DomainError("OPPORTUNITY_NOT_FOUND", f"No opportunity '{oid}'.", 404)
    return row


@handle_errors("list opportunity documents")
def list_opportunity_documents(
    user: CurrentUser, opportunity_repo: OpportunityRepository,
    document_repo: OpportunityDocumentRepository, oid: str,
) -> list[crm_models.OpportunityDocumentOut]:
    opportunity = _get_opportunity_or_404(opportunity_repo, oid)
    _require_read_scope(user, opportunity)
    return [_opportunity_document_out(d) for d in document_repo.list_for_opportunity(oid)]


@handle_errors("add opportunity document")
def add_opportunity_document(
    user: CurrentUser, opportunity_repo: OpportunityRepository,
    document_repo: OpportunityDocumentRepository, oid: str,
    payload: crm_models.OpportunityDocumentCreate,
) -> crm_models.OpportunityDocumentOut:
    opportunity = _get_opportunity_or_404(opportunity_repo, oid)
    _require_write_scope(user, opportunity)
    existing = document_repo.list_for_opportunity(oid)
    next_version = max((d.version_number for d in existing), default=0) + 1
    row = document_repo.create(
        opportunity_id=oid, version_number=next_version, doc_type=payload.doc_type,
        status="UPLOADED", sharepoint_item_id=payload.sharepoint_item_id,
        sharepoint_url=payload.sharepoint_url, filename=payload.filename, uploaded_at=_now(),
        created_by=user.employee_id, updated_by=user.employee_id,
    )
    return _opportunity_document_out(row)


@handle_errors("update opportunity document")
def update_opportunity_document(
    user: CurrentUser, opportunity_repo: OpportunityRepository,
    document_repo: OpportunityDocumentRepository, doc_id: UUID,
    payload: crm_models.OpportunityDocumentUpdate,
) -> crm_models.OpportunityDocumentOut:
    row = document_repo.get(doc_id)
    if row is None:
        raise DomainError("OPPORTUNITY_DOCUMENT_NOT_FOUND", f"No document '{doc_id}'.", 404)
    _require_write_scope(user, _get_opportunity_or_404(opportunity_repo, row.opportunity_id))
    changes = payload.model_dump(exclude_unset=True)
    changes["updated_by"] = user.employee_id
    updated = document_repo.update(doc_id, **changes)
    return _opportunity_document_out(updated)


# --- Campaigns -----------------------------------------------------------------
# Campaign now carries owner_employee_id and its own OWD row (CONTACT and
# CAMPAIGN were added to _OWD_OBJECTS by the migration that introduced record
# sharing). CAMPAIGN's OWD is seeded PUBLIC_READ_WRITE, not PRIVATE like the
# other 4 — deliberately, so every existing campaign (all currently unowned)
# stays visible and editable to anyone with platform.read/campaigns.write
# exactly as before; only NEW campaigns pick up a real owner going forward.
# An admin can tighten CAMPAIGN's OWD later via PUT /org-wide-defaults if
# per-campaign scoping is ever wanted.


def _campaign_out(row: Campaign, user: CurrentUser | None = None) -> crm_models.CampaignOut:
    can_edit, can_delete = _permission_flags(user, row) if user is not None else (True, True)
    return crm_models.CampaignOut(
        id=row.id, name=row.name, campaign_type=row.campaign_type, status=row.status,
        start_date=row.start_date, end_date=row.end_date, description=row.description,
        budgeted_cost=row.budgeted_cost, actual_cost=row.actual_cost,
        expected_revenue=row.expected_revenue, expected_response_pct=row.expected_response_pct,
        num_sent=row.num_sent, parent_campaign_id=row.parent_campaign_id, is_active=row.is_active,
        owner_employee_id=row.owner_employee_id, can_edit=can_edit, can_delete=can_delete,
        created_at=row.created_at, updated_at=row.updated_at,
        created_by=row.created_by, updated_by=row.updated_by,
    )


def _get_campaign_or_404(repo: CampaignRepository, cid) -> Campaign:
    row = repo.get(cid)
    if row is None:
        raise DomainError("CAMPAIGN_NOT_FOUND", f"No campaign '{cid}'.", 404)
    return row


@handle_errors("list campaigns")
def list_campaigns(user: CurrentUser, repo: CampaignRepository) -> list[crm_models.CampaignOut]:
    owd_repo = get_org_wide_default_repository()
    rows = [r for r in repo.list() if _in_read_scope(user, r, owd_repo)]
    rows.sort(key=lambda r: r.created_at, reverse=True)
    return [_campaign_out(r, user) for r in rows]


@handle_errors("create campaign")
def create_campaign(user: CurrentUser, repo: CampaignRepository, employees: EmployeeRepository,
                    payload: crm_models.CampaignCreate) -> crm_models.CampaignOut:
    _validate_owner(employees, payload.owner_employee_id)
    # Same "no explicit owner -> creator becomes owner" rule as
    # create_account()/create_lead(), so a newly created campaign isn't
    # immediately outside its own creator's scope under a PRIVATE CAMPAIGN OWD.
    owner_employee_id = payload.owner_employee_id or verified_employee_uuid(user)
    row = repo.create(
        name=payload.name, campaign_type=payload.campaign_type, status=payload.status,
        start_date=payload.start_date, end_date=payload.end_date, description=payload.description,
        budgeted_cost=payload.budgeted_cost, actual_cost=payload.actual_cost,
        expected_revenue=payload.expected_revenue, expected_response_pct=payload.expected_response_pct,
        num_sent=payload.num_sent, parent_campaign_id=payload.parent_campaign_id, is_active=True,
        owner_employee_id=owner_employee_id,
        created_by=user.employee_id, updated_by=user.employee_id,
    )
    return _campaign_out(row, user)


@handle_errors("get campaign")
def get_campaign(user: CurrentUser, repo: CampaignRepository, cid) -> crm_models.CampaignOut:
    row = _get_campaign_or_404(repo, cid)
    _require_read_scope(user, row, "Campaign is outside your data scope.")
    return _campaign_out(row, user)


@handle_errors("update campaign")
def update_campaign(user: CurrentUser, repo: CampaignRepository, employees: EmployeeRepository, cid,
                    payload: crm_models.CampaignUpdate) -> crm_models.CampaignOut:
    row = _get_campaign_or_404(repo, cid)
    _require_write_scope(user, row, "Campaign is outside your data scope.")
    changes = payload.model_dump(exclude_unset=True)
    if "owner_employee_id" in changes:
        _validate_owner(employees, changes["owner_employee_id"])
    changes["updated_by"] = user.employee_id
    updated = repo.update(cid, **changes)
    return _campaign_out(updated, user)


@handle_errors("delete campaign")
def delete_campaign(user: CurrentUser, repo: CampaignRepository, cid) -> None:
    row = _get_campaign_or_404(repo, cid)
    _require_delete_scope(user, row, "Campaign is outside your data scope.")
    repo.update(cid, updated_by=user.employee_id)
    repo.delete(cid)


@handle_errors("send campaign email")
def send_campaign_email(
    user: CurrentUser, campaign_repo: CampaignRepository, lead_repo: LeadRepository,
    comm_repo: CommunicationRepository, email_sender: EmailSender, cid,
    payload: crm_models.CampaignSendRequest,
) -> crm_models.CampaignSendResult:
    """Targets every Lead with campaign_id == cid, scoped the same as
    list_leads(campaign_id=...) — a SALES caller only reaches leads they own,
    even though the campaign itself isn't ownership-scoped (see the module
    docstring above). Sent one at a time (this is "CRM Lite", not a bulk mail
    provider); one recipient's failure is counted, not raised, so it never
    aborts the rest of the send."""
    campaign = _get_campaign_or_404(campaign_repo, cid)
    owd_repo = get_org_wide_default_repository()
    targets = [r for r in lead_repo.list_for_campaign(campaign.id) if _in_read_scope(user, r, owd_repo)]

    sent = skipped_no_email = skipped_opted_out = failed = 0
    now = _now()
    for lead in targets:
        if lead.email_opt_out:
            skipped_opted_out += 1
            continue
        if not lead.contact_email:
            skipped_no_email += 1
            continue
        try:
            email_sender.send(lead.contact_email, payload.subject, payload.body)
        except DomainError:
            failed += 1
            continue
        comm_repo.create(
            lead_id=lead.id, account_id=None, agreement_id=None,
            direction="OUTBOUND", channel=LeadCommunicationChannel.EMAIL.value,
            subject=payload.subject, to_recipients=lead.contact_email,
            occurred_at=now, source="CAMPAIGN", logged_by_employee_id=None,
            created_by=user.employee_id, updated_by=user.employee_id,
        )
        sent += 1

    if sent:
        campaign_repo.update(campaign.id, num_sent=(campaign.num_sent or 0) + sent,
                             updated_by=user.employee_id)

    return crm_models.CampaignSendResult(
        campaign_id=campaign.id, total_targeted=len(targets), sent=sent,
        skipped_no_email=skipped_no_email, skipped_opted_out=skipped_opted_out, failed=failed,
    )


# --- Leads -----------------------------------------------------------------
# Scope mirrors Account/Opportunity exactly: owner/role-hierarchy/
# records.see_all always applies (see _hierarchy_scope() above), further
# widened per-object by the LEAD Organization-Wide Default — see
# _in_read_scope()/_in_write_scope()/_require_read_scope()/_require_write_scope().


def _lead_out(row: Lead, user: CurrentUser | None = None,
              territory_map: dict[int, str] | None = None) -> crm_models.LeadOut:
    can_edit, can_delete = _permission_flags(user, row) if user is not None else (True, True)
    territories = territory_map if territory_map is not None else _territory_map()
    return crm_models.LeadOut(
        id=row.id, campaign_id=row.campaign_id, account_id=row.account_id, company_name=row.company_name,
        salutation=row.salutation, first_name=row.first_name, last_name=row.last_name,
        title=row.title, contact_email=row.contact_email, contact_phone=row.contact_phone,
        mobile_phone=row.mobile_phone, whatsapp_number=row.whatsapp_number,
        whatsapp_opt_in=row.whatsapp_opt_in, whatsapp_opt_in_source=row.whatsapp_opt_in_source,
        whatsapp_opt_in_at=row.whatsapp_opt_in_at, whatsapp_window_expires_at=row.whatsapp_window_expires_at,
        website=row.website, linkedin_url=row.linkedin_url, industry=row.industry,
        rating=row.rating, annual_revenue=row.annual_revenue, num_employees=row.num_employees,
        address=row.address, country=row.country, state_province=row.state_province,
        city=row.city, postal_code=row.postal_code,
        region=geo.derive_region(row.country, row.state_province),
        description=row.description,
        do_not_call=row.do_not_call, email_opt_out=row.email_opt_out,
        source=row.source, status=row.status, lead_score=row.lead_score,
        web_enrichment_points=row.web_enrichment_points, web_enrichment_summary=row.web_enrichment_summary,
        web_enrichment_at=row.web_enrichment_at, signal_points=row.signal_points,
        owner_employee_id=row.owner_employee_id,
        territory=_territory_code(row.territory_id, territories),
        converted_account_id=row.converted_account_id,
        converted_contact_id=row.converted_contact_id,
        converted_opportunity_id=row.converted_opportunity_id,
        converted_at=row.converted_at,
        can_edit=can_edit, can_delete=can_delete,
        created_at=row.created_at, updated_at=row.updated_at,
        created_by=row.created_by, updated_by=row.updated_by,
    )


def _lead_full_name(lead: Lead) -> str:
    return " ".join(part for part in (lead.first_name, lead.last_name) if part).strip()


def _get_lead_or_404(repo: LeadRepository, lid) -> Lead:
    row = repo.get(lid)
    if row is None:
        raise DomainError("LEAD_NOT_FOUND", f"No lead '{lid}'.", 404)
    return row


#: Lead columns a LeadScoringRule is allowed to reference — kept small and
#: explicit rather than "any column" so a typo'd field_name fails loudly at
#: rule-create time instead of silently never matching.
_SCORABLE_LEAD_FIELDS = {
    "industry", "annual_revenue", "num_employees", "rating", "source",
    "email_opt_out", "do_not_call",
}


def _rule_matches(rule, value) -> bool:
    if rule.operator == LeadScoringOperator.IS_SET.value:
        return value not in (None, "")
    if value is None:
        return False
    if rule.operator == LeadScoringOperator.EQUALS.value:
        return str(value).strip().lower() == (rule.comparison_value or "").strip().lower()
    if rule.operator == LeadScoringOperator.CONTAINS.value:
        return (rule.comparison_value or "").strip().lower() in str(value).strip().lower()
    if rule.operator in (LeadScoringOperator.GREATER_THAN.value, LeadScoringOperator.LESS_THAN.value):
        try:
            numeric_value, threshold = float(value), float(rule.comparison_value)
        except (TypeError, ValueError):
            return False  # unparsable rule config contributes 0 points, doesn't fail the write
        return numeric_value > threshold if rule.operator == LeadScoringOperator.GREATER_THAN.value \
            else numeric_value < threshold
    return False


def _compute_lead_score(fields: dict, rules: list) -> int:
    total = sum(
        rule.points for rule in rules
        if rule.is_active and rule.field_name in fields and _rule_matches(rule, fields[rule.field_name])
    )
    return max(0, total)


def _total_lead_score(
    rule_score: int, web_enrichment_points: int | None, signal_points: int | None = None,
) -> int:
    """lead_score is always rule-based + web-enriched + Pulse-signal
    combined, floored at 0 — kept as one function so create_lead/
    update_lead/generate_web_lead_enrichment/ingest_signals can never drift
    on how the three combine."""
    return max(0, rule_score + (web_enrichment_points or 0) + (signal_points or 0))


#: Main path: NEW -> ATTEMPTING_CONTACT -> CONTACTED -> QUALIFYING ->
#: QUALIFIED -> CONVERTED (CONVERTED happens via convert_lead(), never a
#: plain status PATCH — see the QUALIFIED entry below). NURTURING is a
#: revisitable side branch ("good fit, not ready yet") reachable from most
#: active stages and able to re-enter the path further along when the
#: prospect re-engages (see run_email_intake()'s auto-advance-on-reply).
#: UNQUALIFIED/DISQUALIFIED/CONVERTED are terminal (mirrors
#: _MILESTONE_TRANSITIONS' shape in delivery_service.py: a small dict of
#: allowed next-states per status).
_LEAD_TRANSITIONS: dict[str, set[str]] = {
    LeadStatus.NEW.value: {
        LeadStatus.ATTEMPTING_CONTACT.value, LeadStatus.UNQUALIFIED.value, LeadStatus.DISQUALIFIED.value,
    },
    LeadStatus.ATTEMPTING_CONTACT.value: {
        LeadStatus.CONTACTED.value, LeadStatus.NURTURING.value,
        LeadStatus.UNQUALIFIED.value, LeadStatus.DISQUALIFIED.value,
    },
    LeadStatus.CONTACTED.value: {
        LeadStatus.QUALIFYING.value, LeadStatus.NURTURING.value,
        LeadStatus.UNQUALIFIED.value, LeadStatus.DISQUALIFIED.value,
    },
    LeadStatus.QUALIFYING.value: {
        LeadStatus.QUALIFIED.value, LeadStatus.NURTURING.value,
        LeadStatus.UNQUALIFIED.value, LeadStatus.DISQUALIFIED.value,
    },
    LeadStatus.QUALIFIED.value: {
        LeadStatus.NURTURING.value, LeadStatus.DISQUALIFIED.value,
    },  # CONVERTED happens via convert_lead(), not here
    LeadStatus.NURTURING.value: {
        LeadStatus.CONTACTED.value, LeadStatus.QUALIFYING.value,
        LeadStatus.UNQUALIFIED.value, LeadStatus.DISQUALIFIED.value,
    },
    LeadStatus.UNQUALIFIED.value: set(),
    LeadStatus.DISQUALIFIED.value: set(),
    LeadStatus.CONVERTED.value: set(),
}

#: Statuses run_email_intake() will auto-advance to CONTACTED when a reply
#: comes in from a sender who already has a Lead — anything not in this set
#: (already past first contact, or a terminal/converted state) is left
#: alone; a reply doesn't mean much extra once a real conversation, or an
#: ending, is already on record.
_AUTO_ADVANCE_TO_CONTACTED_FROM = {
    LeadStatus.NEW.value, LeadStatus.ATTEMPTING_CONTACT.value, LeadStatus.NURTURING.value,
}


@handle_errors("list leads")
def list_leads(
    user: CurrentUser, repo: LeadRepository, *,
    campaign_id=None, industry: str | None = None, status: str | None = None,
    owner_employee_id=None, date_from=None, date_to=None,
) -> list[crm_models.LeadOut]:
    """Filters mirror the manager dashboard's axes (see
    platform_service.manager_dashboard()) so a UI can drill from a dashboard
    figure straight into the underlying lead list (BRD MV-3)."""
    owd_repo = get_org_wide_default_repository()
    rows = [r for r in repo.list() if _in_read_scope(user, r, owd_repo)]
    if campaign_id is not None:
        rows = [r for r in rows if r.campaign_id == campaign_id]
    if industry is not None:
        rows = [r for r in rows if (r.industry or "").lower() == industry.lower()]
    if status is not None:
        rows = [r for r in rows if r.status == status.upper()]
    if owner_employee_id is not None:
        rows = [r for r in rows if r.owner_employee_id == owner_employee_id]
    if date_from is not None:
        rows = [r for r in rows if r.created_at.date() >= date_from]
    if date_to is not None:
        rows = [r for r in rows if r.created_at.date() <= date_to]
    rows.sort(key=lambda r: r.created_at, reverse=True)
    fls = get_effective_field_permissions(user, get_field_permission_repository(), "LEAD")
    territory_map = _territory_map()
    return [_redact(_lead_out(r, user, territory_map), fls) for r in rows]


@handle_errors("create lead")
def create_lead(user: CurrentUser, repo: LeadRepository, employees: EmployeeRepository,
                rules_repo: LeadScoringRuleRepository,
                payload: crm_models.LeadCreate,
                account_repo: AccountRepository | None = None,
                *,
                cadence_template_repo: CadenceTemplateRepository | None = None,
                cadence_step_repo: CadenceStepRepository | None = None,
                cadence_enrollment_repo: LeadCadenceEnrollmentRepository | None = None,
                cadence_task_repo: CadenceTaskRepository | None = None) -> crm_models.LeadOut:
    """account_repo is optional so every existing caller (email intake,
    tests) keeps working unchanged — same reasoning as create_opportunity()'s
    asset_repo — it's only required when payload.account_id is actually set.
    The four cadence_* repos are also optional/keyword-only for the same
    reason; when all four are supplied, a brand-new lead is auto-enrolled
    into whichever cadence template is currently Active (BRD Phase 2 #7) —
    see _auto_enroll_new_lead(). Best-effort: any failure there never
    prevents the Lead itself from being created."""
    _validate_owner(employees, payload.owner_employee_id)
    geo.validate_country_state_province(payload.country, payload.state_province)
    if payload.account_id is not None:
        if account_repo is None:
            raise DomainError(
                "ACCOUNT_REPOSITORY_UNAVAILABLE",
                "account_id was supplied but this deployment cannot resolve accounts.", 500)
        _get_or_404(account_repo, payload.account_id)
    # A rep who creates a lead with no explicit owner becomes its owner —
    # otherwise it's immediately outside their own scope the moment they try
    # to act on it (real incident: a SALES rep's own "New lead" submission
    # came back unowned, so their very next click on it 403'd). Resolves to
    # None for a caller with no real, provisioned employee row (dev bypass,
    # the email-intake/bootstrap scripts' synthetic identities) — those
    # leads are meant to land unowned for an AE/ADMIN to triage.
    owner_employee_id = payload.owner_employee_id or verified_employee_uuid(user)
    # Sales Territory/Region — same owner-derived defaulting as
    # create_account()'s identical comment.
    territory_id = _owner_territory_id(employees, owner_employee_id)
    # FLS applies to create too, same as get/update/list — a field this
    # caller can't edit is silently dropped from the payload rather than
    # rejected, matching how a real client (whose UI never rendered that
    # input) would behave. company_name/last_name are excluded from this:
    # they're required at the DB/create level regardless of FLS editability
    # (see crm_models.py — the Optional on the *Out* type is solely for
    # response redaction, not a relaxed create requirement).
    fls = get_effective_field_permissions(user, get_field_permission_repository(), "LEAD")
    changes = _drop_noneditable({
        "campaign_id": payload.campaign_id, "account_id": payload.account_id,
        "salutation": payload.salutation,
        "first_name": payload.first_name, "title": payload.title,
        "contact_email": payload.contact_email, "contact_phone": payload.contact_phone,
        "mobile_phone": payload.mobile_phone, "whatsapp_number": payload.whatsapp_number,
        "website": payload.website,
        "linkedin_url": payload.linkedin_url, "industry": payload.industry,
        "rating": payload.rating, "annual_revenue": payload.annual_revenue,
        "num_employees": payload.num_employees, "address": payload.address,
        "country": payload.country, "state_province": payload.state_province,
        "city": payload.city, "postal_code": payload.postal_code,
        "description": payload.description, "do_not_call": payload.do_not_call,
        "email_opt_out": payload.email_opt_out, "source": payload.source,
    }, fls)
    scoring_fields = {f: changes.get(f) for f in _SCORABLE_LEAD_FIELDS}
    score = _compute_lead_score(scoring_fields, rules_repo.list_active())
    row = repo.create(
        company_name=payload.company_name.strip(), last_name=payload.last_name.strip(),
        **changes,
        status=LeadStatus.NEW.value, lead_score=score,
        owner_employee_id=owner_employee_id,
        territory_id=territory_id,
        created_by=user.employee_id, updated_by=user.employee_id,
    )
    if (cadence_template_repo is not None and cadence_step_repo is not None
            and cadence_enrollment_repo is not None and cadence_task_repo is not None):
        try:
            _auto_enroll_new_lead(
                user, row, cadence_template_repo, cadence_step_repo,
                cadence_enrollment_repo, cadence_task_repo, employees,
            )
        except Exception:  # noqa: BLE001 - best-effort, must never fail lead creation
            pass
    return _redact(_lead_out(row, user), fls)


#: Synthetic caller for POST /email-intake/poll — that endpoint is triggered
#: by a scheduler (see require_email_intake_secret), not a logged-in
#: employee, so there's no real CurrentUser to attribute the created leads
#: to. Same "one legitimate reason to bypass the normal identity" as
#: scripts/bootstrap_admin.py's _BOOTSTRAP_USER.
_EMAIL_INTAKE_USER = CurrentUser(
    employee_id="email-intake", profile_codes={"ADMIN"}, capabilities=set(CAPABILITY_REGISTRY.keys()))


def _company_name_from_sender(address: str) -> str:
    """No real company name exists yet for a cold inbound email — the domain
    is the only signal available, and matches how a rep would eyeball it
    before renaming the lead once they know who actually reached out."""
    domain = address.rsplit("@", 1)[-1] if "@" in address else address
    return domain or "Unknown"


def _name_from_sender(display_name: str | None, address: str) -> tuple[str | None, str]:
    """LeadCreate requires a non-empty last_name; a bare inbound email often
    has no display name at all, so the local part of the address is the
    fallback of last resort."""
    if display_name:
        parts = display_name.strip().split()
        if len(parts) >= 2:
            return parts[0], " ".join(parts[1:])
        if parts:
            return None, parts[0]
    local_part = address.split("@", 1)[0] if "@" in address else address
    return None, local_part or "Unknown"


@handle_errors("run email intake")
def run_email_intake(
    lead_repo: LeadRepository, employees: EmployeeRepository, rules_repo: LeadScoringRuleRepository,
    comm_repo: CommunicationRepository, receiver: InboundEmailReceiver,
    *,
    cadence_template_repo: CadenceTemplateRepository | None = None,
    cadence_step_repo: CadenceStepRepository | None = None,
    cadence_enrollment_repo: LeadCadenceEnrollmentRepository | None = None,
    cadence_task_repo: CadenceTaskRepository | None = None,
) -> crm_models.EmailIntakeResult:
    """A sender who already has a Lead (matched by contact_email) gets an
    INBOUND Communication logged against it — no duplicate lead, and if the
    lead hasn't had a real conversation start yet (see
    _AUTO_ADVANCE_TO_CONTACTED_FROM), a reply is exactly that signal, so its
    status auto-advances to CONTACTED. A new sender becomes a fresh, unowned
    Lead (source=EMAIL) for an AE/ADMIN to triage and assign, same as any
    other unowned lead's visibility (see _hierarchy_scope() above) — SALES doesn't
    see it until it's assigned to them. One message's failure is counted,
    not raised, so it never aborts the rest of the poll. The cadence_* repos
    (optional, same reasoning as create_lead()'s) let a cold-inbound-email
    lead get auto-enrolled into the Active cadence exactly like one created
    from the UI."""
    messages = receiver.fetch_unseen()
    leads_created = matched_existing = errors = 0
    for msg in messages:
        try:
            # Idempotent regardless of the mailbox's \Seen flag state — if
            # this exact message was already ingested (e.g. a re-poll after
            # the flag got reset), skip it outright rather than logging a
            # second INBOUND Communication for it.
            if msg.message_id and comm_repo.find_by_graph_message_id(msg.message_id) is not None:
                continue
            existing = lead_repo.find_by_contact_email(msg.from_address)
            if existing is not None:
                lead_id = existing.id
                matched_existing += 1
                if existing.status in _AUTO_ADVANCE_TO_CONTACTED_FROM:
                    lead_repo.update(
                        lead_id, status=LeadStatus.CONTACTED.value,
                        updated_by=_EMAIL_INTAKE_USER.employee_id,
                    )
            else:
                first_name, last_name = _name_from_sender(msg.from_name, msg.from_address)
                created = create_lead(
                    _EMAIL_INTAKE_USER, lead_repo, employees, rules_repo,
                    crm_models.LeadCreate(
                        company_name=_company_name_from_sender(msg.from_address),
                        first_name=first_name, last_name=last_name, contact_email=msg.from_address,
                        description=(msg.body or "").strip()[:2000] or None, source="EMAIL",
                    ),
                    cadence_template_repo=cadence_template_repo, cadence_step_repo=cadence_step_repo,
                    cadence_enrollment_repo=cadence_enrollment_repo, cadence_task_repo=cadence_task_repo,
                )
                lead_id = created.id
                leads_created += 1
            comm_repo.create(
                lead_id=lead_id, account_id=None, agreement_id=None,
                direction="INBOUND", channel=LeadCommunicationChannel.EMAIL.value,
                subject=msg.subject, body=msg.body, from_address=msg.from_address,
                graph_message_id=msg.message_id,
                occurred_at=msg.received_at, source="EMAIL_INTAKE", logged_by_employee_id=None,
                created_by=_EMAIL_INTAKE_USER.employee_id, updated_by=_EMAIL_INTAKE_USER.employee_id,
            )
        except DomainError:
            errors += 1
    return crm_models.EmailIntakeResult(
        messages_processed=len(messages), leads_created=leads_created,
        matched_existing_lead=matched_existing, errors=errors,
    )


#: created_by/updated_by stamp for Communications logged from the Twilio
#: webhook — same "one legitimate reason to bypass the normal identity" as
#: _EMAIL_INTAKE_USER above, but plain string is enough here: unlike
#: run_email_intake(), this never calls create_lead() (see
#: process_inbound_sms()'s docstring for why), so no CurrentUser with real
#: capabilities is ever needed.
_SMS_INTAKE_USER_ID = "sms-intake"


@handle_errors("process inbound sms")
def process_inbound_sms(
    lead_repo: LeadRepository, comm_repo: CommunicationRepository, *,
    from_number: str, body: str, message_sid: str,
) -> crm_models.SmsIntakeResult:
    """The SMS half of message intake, called once per Twilio webhook hit
    (one call = one inbound text, unlike run_email_intake()'s poll-many
    shape) — see utils.security.require_twilio_signature for how the caller
    is authenticated.

    Unlike run_email_intake(), an unmatched sender does NOT get a new Lead
    auto-created: Lead.contact_email is required (NOT NULL) and an inbound
    SMS carries no email address to satisfy it, so a text from a number not
    already on file (Lead.contact_phone/mobile_phone, via
    lead_repo.find_by_phone()) is simply not logged against any record —
    matched_lead=False in the response is the signal an AE/ADMIN needs to
    go create that Lead (with a real contact_email) by hand first."""
    if message_sid:
        existing = comm_repo.find_by_provider_message_id(message_sid)
        if existing is not None:
            return crm_models.SmsIntakeResult(
                matched_lead=existing.lead_id is not None, lead_id=existing.lead_id,
                communication_id=existing.id, duplicate=True)

    lead = lead_repo.find_by_phone(from_number)
    if lead is None:
        return crm_models.SmsIntakeResult(matched_lead=False)

    row = comm_repo.create(
        lead_id=lead.id, account_id=None, agreement_id=None,
        direction="INBOUND", channel=LeadCommunicationChannel.SMS.value,
        body=body, from_address=from_number, provider_message_id=message_sid or None,
        occurred_at=datetime.now(timezone.utc), source="SMS_INTAKE", logged_by_employee_id=None,
        created_by=_SMS_INTAKE_USER_ID, updated_by=_SMS_INTAKE_USER_ID,
    )
    return crm_models.SmsIntakeResult(matched_lead=True, lead_id=lead.id, communication_id=row.id)


@handle_errors("get lead")
def get_lead(user: CurrentUser, repo: LeadRepository, lid) -> crm_models.LeadOut:
    row = _get_lead_or_404(repo, lid)
    _require_read_scope(user, row, "Lead is outside your data scope.")
    fls = get_effective_field_permissions(user, get_field_permission_repository(), "LEAD")
    return _redact(_lead_out(row, user), fls)


@handle_errors("get lead score breakdown")
def get_lead_score_breakdown(
    user: CurrentUser, repo: LeadRepository, rules_repo: LeadScoringRuleRepository, lid,
) -> list[crm_models.LeadScoreBreakdownEntry]:
    row = _get_lead_or_404(repo, lid)
    _require_read_scope(user, row, "Lead is outside your data scope.")
    fields = {f: getattr(row, f) for f in _SCORABLE_LEAD_FIELDS}
    return [
        crm_models.LeadScoreBreakdownEntry(rule_id=rule.id, name=rule.name, points=rule.points)
        for rule in rules_repo.list_active()
        if rule.field_name in fields and _rule_matches(rule, fields[rule.field_name])
    ]


@handle_errors("update lead")
def update_lead(user: CurrentUser, repo: LeadRepository, employees: EmployeeRepository,
                rules_repo: LeadScoringRuleRepository,
                lid, payload: crm_models.LeadUpdate,
                account_repo: AccountRepository | None = None) -> crm_models.LeadOut:
    row = _get_lead_or_404(repo, lid)
    _require_write_scope(user, row, "Lead is outside your data scope.")
    fls = get_effective_field_permissions(user, get_field_permission_repository(), "LEAD")
    changes = _drop_noneditable(payload.model_dump(exclude_unset=True), fls)
    if "owner_employee_id" in changes:
        _validate_owner(employees, changes["owner_employee_id"])
    if changes.get("account_id") is not None:
        if account_repo is None:
            raise DomainError(
                "ACCOUNT_REPOSITORY_UNAVAILABLE",
                "account_id was supplied but this deployment cannot resolve accounts.", 500)
        _get_or_404(account_repo, changes["account_id"])
    # Same reasoning as update_account()'s identical check — validate the
    # resulting pair, not just whichever half this patch happens to touch.
    if "country" in changes or "state_province" in changes:
        geo.validate_country_state_province(
            changes.get("country", row.country),
            changes.get("state_province", row.state_province),
        )
    new_status = changes.get("status")
    if new_status is not None and new_status != row.status:
        allowed = _LEAD_TRANSITIONS.get(row.status, set())
        if new_status not in allowed:
            raise DomainError(
                "LEAD_STATUS_TRANSITION_INVALID",
                f"Cannot move a lead from {row.status} to {new_status}.", 422)
    scoring_fields = {f: changes.get(f, getattr(row, f)) for f in _SCORABLE_LEAD_FIELDS}
    rule_score = _compute_lead_score(scoring_fields, rules_repo.list_active())
    changes["lead_score"] = _total_lead_score(rule_score, row.web_enrichment_points, row.signal_points)
    changes["updated_by"] = user.employee_id
    updated = repo.update(lid, **changes)
    return _redact(_lead_out(updated, user), fls)


@handle_errors("flag lead hot")
def flag_lead_hot(user: CurrentUser, repo: LeadRepository,
                  notification_repo: NotificationRepository, lid) -> crm_models.LeadOut:
    """LEADERSHIP's one narrow write path onto Lead — see
    permissions.py's leads.flag_hot docstring. Deliberately just sets
    rating; no scope check, matching manager_dashboard.read's own
    cross-team, no-ownership-scoping visibility (leadership needs to be
    able to flag ANY rep's lead, not just their own). Notifies the lead's
    owner, if it has one — the whole point of flagging a lead HOT from the
    manager dashboard is to tell that rep to act on it now; an unowned lead
    has nobody to notify yet (an AE/ADMIN will see it's HOT once assigned)."""
    row = _get_lead_or_404(repo, lid)
    updated = repo.update(lid, rating="HOT", updated_by=user.employee_id)
    if row.owner_employee_id is not None:
        contact = _lead_full_name(row)
        who = f"{contact} ({row.company_name})" if contact else row.company_name
        notification_repo.create(
            lead_id=row.id, recipient_employee_id=row.owner_employee_id,
            notification_type="LEAD_FLAGGED_HOT", severity="INFO",
            message=f"{who} was flagged HOT — follow up now.",
            sent_at=_now(), created_by=user.employee_id, updated_by=user.employee_id,
        )
    return _lead_out(updated, user)


@handle_errors("delete lead")
def delete_lead(user: CurrentUser, repo: LeadRepository, lid) -> None:
    row = _get_lead_or_404(repo, lid)
    _require_delete_scope(user, row, "Lead is outside your data scope.")
    repo.update(lid, updated_by=user.employee_id)
    repo.delete(lid)


@handle_errors("convert lead")
def convert_lead(user: CurrentUser, lead_repo: LeadRepository, account_repo: AccountRepository,
                 contact_repo: ContactRepository, opportunity_repo: OpportunityRepository,
                 employees: EmployeeRepository, lid, payload: crm_models.LeadConvertRequest,
                 ) -> crm_models.LeadOut:
    """The one atomic action in this module: a QUALIFIED lead becomes a
    Account + Contact + Opportunity together, exactly the trio Salesforce's
    own Convert Lead produces (Account is this system's Account-equivalent —
    see the module docstring in crm_models.py). Composes create_account/
    add_contact/create_opportunity (never reimplements their rules), then
    stamps attribution (lead_id/campaign_id) onto the new Opportunity and
    marks the Lead Converted with references to all three new rows —
    mirroring Salesforce's ConvertedAccountId/ConvertedContactId/
    ConvertedOpportunityId. Never reversible, same as promote_account()."""
    lead = _get_lead_or_404(lead_repo, lid)
    _require_write_scope(user, lead, "Lead is outside your data scope.")
    if lead.status == LeadStatus.CONVERTED.value:
        raise DomainError("LEAD_ALREADY_CONVERTED", "This lead has already been converted.", 409)
    if lead.status != LeadStatus.QUALIFIED.value:
        raise DomainError(
            "LEAD_NOT_QUALIFIED",
            "Only a Qualified (Opportunity) lead can be converted — move it through "
            "Attempting Contact, Contacted, and Qualifying first.", 422)

    new_account = create_account(
        user, account_repo, employees,
        crm_models.AccountCreate(legal_name=lead.company_name, owner_employee_id=lead.owner_employee_id),
    )
    new_contact = add_contact(
        user, account_repo, contact_repo, new_account.id,
        crm_models.ContactCreate(
            contact_type="BUSINESS", full_name=_lead_full_name(lead),
            email=lead.contact_email, phone=lead.contact_phone, title=lead.title,
            is_primary=True,
        ),
    )
    new_opportunity = create_opportunity(
        user, account_repo, opportunity_repo,
        crm_models.OpportunityCreate(
            account_id=new_account.id, name=payload.opportunity_name,
            estimated_value=payload.estimated_value, currency=payload.currency,
            expected_close_date=payload.expected_close_date, owner_employee_id=lead.owner_employee_id,
        ),
    )
    # OpportunityCreate has no lead_id/campaign_id field (a client never sets
    # attribution directly — see crm_models.py) — stamp it here, the one place
    # that's allowed to.
    opportunity_repo.update(new_opportunity.id, lead_id=lead.id, campaign_id=lead.campaign_id,
                            updated_by=user.employee_id)

    now = _now()
    converted = lead_repo.update(
        lid, status=LeadStatus.CONVERTED.value,
        converted_account_id=new_account.id, converted_contact_id=new_contact.id,
        converted_opportunity_id=new_opportunity.id, converted_at=now,
        updated_by=user.employee_id,
    )
    return _lead_out(converted, user)


# --- Lead scoring rules --------------------------------------------------------
# Global, admin-managed config — no owner scoping, same treatment as Campaign.
# Rule changes are prospective only: a lead's score is recomputed the next
# time create_lead/update_lead touches it, never retroactively bulk-rewritten
# when a rule itself changes (see _compute_lead_score()'s call sites above).


def _lead_scoring_rule_out(row) -> crm_models.LeadScoringRuleOut:
    return crm_models.LeadScoringRuleOut(
        id=row.id, name=row.name, field_name=row.field_name, operator=row.operator,
        comparison_value=row.comparison_value, points=row.points, is_active=row.is_active,
        created_at=row.created_at, updated_at=row.updated_at,
        created_by=row.created_by, updated_by=row.updated_by,
    )


def _get_lead_scoring_rule_or_404(repo: LeadScoringRuleRepository, rid):
    row = repo.get(rid)
    if row is None:
        raise DomainError("LEAD_SCORING_RULE_NOT_FOUND", f"No lead scoring rule '{rid}'.", 404)
    return row


def _validate_lead_scoring_rule(field_name: str | None, operator: str | None,
                                comparison_value: str | None) -> None:
    if field_name is not None and field_name not in _SCORABLE_LEAD_FIELDS:
        raise DomainError(
            "LEAD_SCORING_FIELD_INVALID",
            f"'{field_name}' is not a scorable lead field. Choose from: "
            f"{', '.join(sorted(_SCORABLE_LEAD_FIELDS))}.", 422)
    if operator is not None:
        try:
            LeadScoringOperator(operator)
        except ValueError:
            raise DomainError(
                "LEAD_SCORING_OPERATOR_INVALID",
                f"'{operator}' is not a valid operator. Choose from: "
                f"{', '.join(o.value for o in LeadScoringOperator)}.", 422) from None
        if operator != LeadScoringOperator.IS_SET.value and not comparison_value:
            raise DomainError(
                "LEAD_SCORING_COMPARISON_VALUE_REQUIRED",
                "comparison_value is required for every operator except IS_SET.", 422)


@handle_errors("list lead scoring rules")
def list_lead_scoring_rules(user: CurrentUser,
                            repo: LeadScoringRuleRepository) -> list[crm_models.LeadScoringRuleOut]:
    rows = sorted(repo.list(), key=lambda r: r.created_at, reverse=True)
    return [_lead_scoring_rule_out(r) for r in rows]


@handle_errors("create lead scoring rule")
def create_lead_scoring_rule(user: CurrentUser, repo: LeadScoringRuleRepository,
                             payload: crm_models.LeadScoringRuleCreate) -> crm_models.LeadScoringRuleOut:
    _validate_lead_scoring_rule(payload.field_name, payload.operator, payload.comparison_value)
    row = repo.create(
        name=payload.name, field_name=payload.field_name, operator=payload.operator,
        comparison_value=payload.comparison_value, points=payload.points, is_active=True,
        created_by=user.employee_id, updated_by=user.employee_id,
    )
    return _lead_scoring_rule_out(row)


@handle_errors("get lead scoring rule")
def get_lead_scoring_rule(user: CurrentUser, repo: LeadScoringRuleRepository,
                          rid) -> crm_models.LeadScoringRuleOut:
    return _lead_scoring_rule_out(_get_lead_scoring_rule_or_404(repo, rid))


@handle_errors("update lead scoring rule")
def update_lead_scoring_rule(user: CurrentUser, repo: LeadScoringRuleRepository, rid,
                             payload: crm_models.LeadScoringRuleUpdate) -> crm_models.LeadScoringRuleOut:
    row = _get_lead_scoring_rule_or_404(repo, rid)
    changes = payload.model_dump(exclude_unset=True)
    _validate_lead_scoring_rule(
        changes.get("field_name", row.field_name),
        changes.get("operator", row.operator),
        changes.get("comparison_value", row.comparison_value),
    )
    changes["updated_by"] = user.employee_id
    updated = repo.update(rid, **changes)
    return _lead_scoring_rule_out(updated)


@handle_errors("delete lead scoring rule")
def delete_lead_scoring_rule(user: CurrentUser, repo: LeadScoringRuleRepository, rid) -> None:
    _get_lead_scoring_rule_or_404(repo, rid)
    repo.update(rid, updated_by=user.employee_id)
    repo.delete(rid)


# --- Field-Level Security -----------------------------------------------------
# Admin-configurable per-(role, object, field) visibility/editability, layered
# on top of (never replacing) the object-level capability grants (see
# utils.permissions.CAPABILITY_REGISTRY) and row-level ownership scoping
# above. No row for a (role, object, field) means
# fully permissive — restrictions are opt-in, so the feature ships inert until
# an admin actually configures something.

#: The only fields FLS can touch, per object — deliberately excludes
#: structural/workflow fields (id, status/stage, owner_employee_id, audit
#: timestamps) that existing UI logic (the stage bar, transition buttons, the
#: Convert gate, the Assign-owner flow) depends on always being able to read.
#: Redacting those would silently break working functionality for no real
#: security benefit — ownership/workflow-state visibility is a different,
#: already-solved problem (RBAC + row scoping), not what FLS is for.
_FLS_FIELDS: dict[str, set[str]] = {
    "LEAD": {
        "company_name", "salutation", "first_name", "last_name", "title",
        "contact_email", "contact_phone", "mobile_phone", "website", "linkedin_url",
        "industry", "rating", "annual_revenue", "num_employees", "address",
        "country", "state_province", "city", "postal_code",
        "description", "do_not_call", "email_opt_out", "source", "campaign_id",
        "account_id",
    },
    "ACCOUNT": {
        "legal_name", "account_site", "industry", "website", "phone", "address",
        "shipping_address", "billing_country", "billing_state_province",
        "shipping_country", "shipping_state_province",
        "billing_city", "billing_postal_code", "shipping_city", "shipping_postal_code",
        "annual_revenue", "num_employees", "ownership",
        "ticker_symbol", "rating", "account_number", "sic_code", "description",
        "parent_account_id",
    },
    "OPPORTUNITY": {
        "name", "estimated_value", "currency", "expected_close_date", "lost_reason",
        "probability_percent", "opportunity_type", "next_step", "description",
    },
}

_FULLY_PERMISSIVE = crm_models.EffectiveFieldPermission(visible=True, editable=True)


def _field_permission_out(row) -> crm_models.FieldPermissionEntry:
    return crm_models.FieldPermissionEntry(
        id=row.id, role_id=row.role_id, object_name=row.object_name,
        field_name=row.field_name, visible=row.visible, editable=row.editable,
    )


@handle_errors("list field permissions")
def list_field_permissions(
    user: CurrentUser, repo: FieldPermissionRepository, object_name: str,
) -> list[crm_models.FieldPermissionEntry]:
    if object_name not in _FLS_FIELDS:
        raise DomainError("FLS_OBJECT_UNKNOWN", f"'{object_name}' is not an FLS-eligible object.", 422)
    rows = sorted(repo.list_for_object(object_name), key=lambda r: (r.role_id, r.field_name))
    return [_field_permission_out(r) for r in rows]


@handle_errors("save field permissions")
def save_field_permissions(
    user: CurrentUser, repo: FieldPermissionRepository,
    payload: crm_models.FieldPermissionSaveRequest,
) -> list[crm_models.FieldPermissionEntry]:
    """Full replace for one object — an admin's matrix Save submits the
    complete desired state in one call, simpler and far less error-prone
    than a per-cell create/update/delete dance for a checkbox grid."""
    object_name = payload.object_name
    if object_name not in _FLS_FIELDS:
        raise DomainError("FLS_OBJECT_UNKNOWN", f"'{object_name}' is not an FLS-eligible object.", 422)
    eligible = _FLS_FIELDS[object_name]
    role_repo = get_profile_repository()

    for entry in payload.entries:
        if entry.object_name != object_name:
            raise DomainError(
                "FLS_OBJECT_MISMATCH", "Every entry's object_name must match the request's object_name.", 422)
        if entry.field_name not in eligible:
            raise DomainError(
                "FLS_FIELD_NOT_ELIGIBLE",
                f"'{entry.field_name}' is not an FLS-eligible field on {object_name}.", 422)
        if entry.editable and not entry.visible:
            raise DomainError(
                "FLS_EDITABLE_REQUIRES_VISIBLE",
                f"'{entry.field_name}' can't be editable without also being visible.", 422)
        role_row = role_repo.get(entry.role_id)
        if role_row is None:
            raise DomainError("ROLE_NOT_FOUND", f"No role '{entry.role_id}'.", 404)
        if role_row.code == "ADMIN":
            raise DomainError(
                "FLS_CANNOT_RESTRICT_ADMIN", "Admin's access can't be restricted by field permissions.", 422)

    for existing in repo.list_for_object(object_name):
        repo.hard_delete(existing.id)
    created = [
        repo.create(
            role_id=entry.role_id, object_name=object_name, field_name=entry.field_name,
            visible=entry.visible, editable=entry.editable,
            created_by=user.employee_id, updated_by=user.employee_id,
        )
        for entry in payload.entries
    ]
    return [_field_permission_out(r) for r in created]


@handle_errors("get effective field permissions")
def get_effective_field_permissions(
    user: CurrentUser, repo: FieldPermissionRepository, object_name: str,
) -> dict[str, crm_models.EffectiveFieldPermission]:
    """Fully permissive baseline for every FLS-eligible field on this
    object, narrowed only where EVERY profile the caller holds has an
    explicit restricting row for that field — union/most-permissive-wins for
    multi-profile employees: a profile with NO row at all is unrestricted,
    and one unrestricted held profile alone is enough to keep a field fully
    permissive regardless of what any other held profile says. ADMIN is
    always fully permissive and never narrowed."""
    eligible = _FLS_FIELDS.get(object_name, set())
    effective = {f: _FULLY_PERMISSIVE for f in eligible}
    if not eligible or "ADMIN" in user.profile_codes:
        return effective

    held_codes = user.profile_codes
    role_ids = {row.id for row in get_profile_repository().list() if row.code in held_codes}
    if not role_ids:
        return effective

    by_field: dict[str, list] = {}
    for row in repo.list_for_object(object_name):
        if row.role_id in role_ids:
            by_field.setdefault(row.field_name, []).append(row)

    for field, field_rows in by_field.items():
        if field not in effective or len(field_rows) < len(role_ids):
            continue  # some held role has no row at all -> that role alone grants full access
        effective[field] = crm_models.EffectiveFieldPermission(
            visible=any(r.visible for r in field_rows), editable=any(r.editable for r in field_rows),
        )
    return effective


#: Objects an Organization-Wide Default row exists for — one row per object,
#: not per (object, field) the way FieldPermission/_FLS_FIELDS is. Also the
#: full set of objects services/record_access_service.py governs.
_OWD_OBJECTS = {"LEAD", "ACCOUNT", "CONTACT", "OPPORTUNITY", "CAMPAIGN"}


@handle_errors("get org-wide defaults")
def get_org_wide_defaults(user: CurrentUser, repo: OrgWideDefaultRepository) -> crm_models.OrgWideDefaultsOut:
    rows = {r.object_name: r.access_level for r in repo.list()}
    # Defensive: fall back to PRIVATE for any object missing its seeded row
    # (shouldn't happen once the introducing migration has run).
    return crm_models.OrgWideDefaultsOut(
        defaults={obj: rows.get(obj, OrgWideDefaultAccessLevel.PRIVATE.value) for obj in _OWD_OBJECTS})


@handle_errors("save org-wide defaults")
def save_org_wide_defaults(
    user: CurrentUser, repo: OrgWideDefaultRepository, payload: crm_models.OrgWideDefaultsSaveRequest,
) -> crm_models.OrgWideDefaultsOut:
    """Full replace, mirrors save_field_permissions()'s reasoning — only 3
    keys ever exist, so every save must submit the complete set rather than
    leaving "was this object omitted on purpose or left as-is" ambiguous."""
    submitted = {e.object_name for e in payload.entries}
    missing = _OWD_OBJECTS - submitted
    if missing:
        raise DomainError(
            "OWD_INCOMPLETE_SUBMISSION",
            f"Every OWD object must be submitted together. Missing: {', '.join(sorted(missing))}.", 422)
    unknown = submitted - _OWD_OBJECTS
    if unknown:
        raise DomainError(
            "OWD_OBJECT_UNKNOWN", f"'{', '.join(sorted(unknown))}' is not an OWD-eligible object.", 422)
    valid_levels = {lvl.value for lvl in OrgWideDefaultAccessLevel}
    for entry in payload.entries:
        if entry.access_level not in valid_levels:
            raise DomainError(
                "OWD_ACCESS_LEVEL_INVALID",
                f"'{entry.access_level}' is not a valid access level. Choose from: "
                f"{', '.join(sorted(valid_levels))}.", 422)

    by_object = {r.object_name: r for r in repo.list()}
    for entry in payload.entries:
        existing = by_object.get(entry.object_name)
        if existing is not None:
            repo.update(existing.id, access_level=entry.access_level, updated_by=user.employee_id)
    return get_org_wide_defaults(user, repo)


# --- Record Sharing ----------------------------------------------------------
# User-based Salesforce-style sharing — see services/record_access_service.py.
# READ|EDIT only, never DELETE (models.enums.RecordAccessLevel / RecordShare's
# docstring), and only ever ADDS access on top of OWD/ownership. Deliberately
# no role/team/group targeting — shared_with_employee_id only.

def _record_share_out(row) -> crm_models.RecordShareOut:
    return crm_models.RecordShareOut(
        id=row.id, object_name=row.object_name, record_id=row.record_id,
        shared_with_employee_id=row.shared_with_employee_id, access_level=row.access_level,
        granted_by=row.granted_by, granted_at=row.granted_at,
        created_at=row.created_at, updated_at=row.updated_at,
        created_by=row.created_by, updated_by=row.updated_by,
    )


def _parse_share_record_uuid(record_id: str, object_name: str) -> UUID:
    try:
        return UUID(record_id)
    except ValueError as exc:
        raise DomainError(
            "RECORD_SHARE_RECORD_ID_INVALID",
            f"'{record_id}' is not a valid id for a {object_name.title()}.", 422) from exc


def _resolve_shareable_record(
    object_name: str, record_id: str, *,
    lead_repo: LeadRepository, account_repo: AccountRepository, contact_repo: ContactRepository,
    opportunity_repo: OpportunityRepository, campaign_repo: CampaignRepository,
):
    """record_id's real type differs per object — Account/Opportunity use
    human-readable business ids (plain strings, e.g. "ACC-00042"/"OPP-00031");
    Lead/Contact/Campaign use UUIDs — parsed here before the lookup."""
    if object_name not in _OWD_OBJECTS:
        raise DomainError(
            "RECORD_SHARE_OBJECT_INVALID", f"'{object_name}' is not a shareable object.", 422)
    row: Lead | Account | Contact | Opportunity | Campaign | None
    if object_name == "LEAD":
        row = lead_repo.get(_parse_share_record_uuid(record_id, object_name))
    elif object_name == "ACCOUNT":
        row = account_repo.get(record_id)
    elif object_name == "CONTACT":
        row = contact_repo.get(_parse_share_record_uuid(record_id, object_name))
    elif object_name == "CAMPAIGN":
        row = campaign_repo.get(_parse_share_record_uuid(record_id, object_name))
    else:
        row = opportunity_repo.get(record_id)
    if row is None:
        raise DomainError(
            "RECORD_SHARE_TARGET_NOT_FOUND", f"No {object_name.title()} '{record_id}'.", 404)
    return row


@handle_errors("list record shares")
def list_record_shares(
    user: CurrentUser, share_repo: RecordShareRepository, object_name: str, record_id: str, *,
    lead_repo: LeadRepository, account_repo: AccountRepository, contact_repo: ContactRepository,
    opportunity_repo: OpportunityRepository, campaign_repo: CampaignRepository,
) -> list[crm_models.RecordShareOut]:
    row = _resolve_shareable_record(
        object_name, record_id, lead_repo=lead_repo, account_repo=account_repo,
        contact_repo=contact_repo, opportunity_repo=opportunity_repo, campaign_repo=campaign_repo)
    _require_read_scope(user, row, f"{object_name.title()} is outside your data scope.")
    return [_record_share_out(s) for s in share_repo.list_for_record(object_name, str(row.id))]


@handle_errors("create record share")
def create_record_share(
    user: CurrentUser, share_repo: RecordShareRepository, employees: EmployeeRepository,
    payload: crm_models.RecordShareCreate, *,
    lead_repo: LeadRepository, account_repo: AccountRepository, contact_repo: ContactRepository,
    opportunity_repo: OpportunityRepository, campaign_repo: CampaignRepository,
) -> crm_models.RecordShareOut:
    """A caller must already be able to EDIT the target record to grant a
    share on it — otherwise a read-only user could hand out access they
    don't themselves have (self-escalation via a proxy). access_level is
    validated to READ|EDIT only: sharing can never grant DELETE."""
    row = _resolve_shareable_record(
        payload.object_name, payload.record_id, lead_repo=lead_repo, account_repo=account_repo,
        contact_repo=contact_repo, opportunity_repo=opportunity_repo, campaign_repo=campaign_repo)
    _require_write_scope(user, row, f"{payload.object_name.title()} is outside your data scope.")
    if payload.access_level not in (RecordAccessLevel.READ.value, RecordAccessLevel.EDIT.value):
        raise DomainError(
            "RECORD_SHARE_ACCESS_LEVEL_INVALID",
            "access_level must be READ or EDIT — sharing can never grant DELETE.", 422)
    if employees.get(payload.shared_with_employee_id) is None:
        raise DomainError(
            "UNKNOWN_EMPLOYEE",
            f"shared_with_employee_id {payload.shared_with_employee_id} does not match any employee.", 400)

    now = _now()
    granted_by = verified_employee_uuid(user)
    existing = share_repo.get_for_employee(payload.object_name, str(row.id), payload.shared_with_employee_id)
    if existing is not None:
        # Re-sharing with the same employee updates the grant in place
        # (e.g. READ -> EDIT) rather than erroring on the unique index.
        updated = share_repo.update(
            existing.id, access_level=payload.access_level, granted_by=granted_by, granted_at=now,
            updated_by=user.employee_id)
        return _record_share_out(updated)
    created = share_repo.create(
        object_name=payload.object_name, record_id=str(row.id),
        shared_with_employee_id=payload.shared_with_employee_id, access_level=payload.access_level,
        granted_by=granted_by, granted_at=now,
        created_by=user.employee_id, updated_by=user.employee_id,
    )
    return _record_share_out(created)


@handle_errors("delete record share")
def delete_record_share(
    user: CurrentUser, share_repo: RecordShareRepository, share_id, *,
    lead_repo: LeadRepository, account_repo: AccountRepository, contact_repo: ContactRepository,
    opportunity_repo: OpportunityRepository, campaign_repo: CampaignRepository,
) -> None:
    share = share_repo.get(share_id)
    if share is None:
        raise DomainError("RECORD_SHARE_NOT_FOUND", f"No record share '{share_id}'.", 404)
    row = _resolve_shareable_record(
        share.object_name, share.record_id, lead_repo=lead_repo, account_repo=account_repo,
        contact_repo=contact_repo, opportunity_repo=opportunity_repo, campaign_repo=campaign_repo)
    _require_write_scope(user, row, f"{share.object_name.title()} is outside your data scope.")
    share_repo.update(share_id, updated_by=user.employee_id)
    share_repo.delete(share_id)


def _redact(out_obj, effective: dict[str, crm_models.EffectiveFieldPermission]):
    for field, perm in effective.items():
        if not perm.visible:
            setattr(out_obj, field, None)
    return out_obj


def _drop_noneditable(changes: dict, effective: dict[str, crm_models.EffectiveFieldPermission]) -> dict:
    """Silently ignores a restricted field in a write payload rather than
    422ing — mirrors what a real client (the UI, which never renders the
    input for a non-editable field) would send in the first place."""
    return {k: v for k, v in changes.items() if effective.get(k, _FULLY_PERMISSIVE).editable}


# --- Product catalog ---------------------------------------------------------
# Global, admin-authored config (no owner scoping, same as
# Campaign/LeadScoringRule) — see generate_email_draft()/generate_call_prep()
# for how the active catalog is used to ground AI drafts in what we actually
# sell rather than a generic pitch.


def _product_out(row) -> crm_models.ProductOut:
    return crm_models.ProductOut(
        id=row.id, name=row.name, description=row.description,
        target_industry=row.target_industry, is_active=row.is_active,
        created_at=row.created_at, updated_at=row.updated_at,
        created_by=row.created_by, updated_by=row.updated_by,
    )


def _get_product_or_404(repo: ProductRepository, pid):
    row = repo.get(pid)
    if row is None:
        raise DomainError("PRODUCT_NOT_FOUND", f"No product '{pid}'.", 404)
    return row


@handle_errors("list products")
def list_products(user: CurrentUser, repo: ProductRepository) -> list[crm_models.ProductOut]:
    rows = sorted(repo.list(), key=lambda r: r.created_at, reverse=True)
    return [_product_out(r) for r in rows]


@handle_errors("create product")
def create_product(user: CurrentUser, repo: ProductRepository,
                   payload: crm_models.ProductCreate) -> crm_models.ProductOut:
    row = repo.create(
        name=payload.name, description=payload.description, target_industry=payload.target_industry,
        is_active=True, created_by=user.employee_id, updated_by=user.employee_id,
    )
    return _product_out(row)


@handle_errors("get product")
def get_product(user: CurrentUser, repo: ProductRepository, pid) -> crm_models.ProductOut:
    return _product_out(_get_product_or_404(repo, pid))


@handle_errors("update product")
def update_product(user: CurrentUser, repo: ProductRepository, pid,
                   payload: crm_models.ProductUpdate) -> crm_models.ProductOut:
    _get_product_or_404(repo, pid)
    changes = payload.model_dump(exclude_unset=True)
    changes["updated_by"] = user.employee_id
    updated = repo.update(pid, **changes)
    return _product_out(updated)


@handle_errors("delete product")
def delete_product(user: CurrentUser, repo: ProductRepository, pid) -> None:
    _get_product_or_404(repo, pid)
    repo.update(pid, updated_by=user.employee_id)
    repo.delete(pid)


# --- Sales Cadence ---------------------------------------------------------------
# Templates/steps are global, admin-authored config (no owner scoping, same as
# Campaign/LeadScoringRule). Enrollments/tasks hang off a Lead, so scope is
# re-derived from the parent Lead via _require_read_scope()/_require_write_scope() — the same
# "check scope against the parent row" idiom list_contacts()/add_contact()
# already use for Contact rows hanging off an Account.


def _cadence_step_out(row: CadenceStep) -> crm_models.CadenceStepOut:
    return crm_models.CadenceStepOut(
        id=row.id, cadence_template_id=row.cadence_template_id, step_order=row.step_order,
        step_type=row.step_type, subject=row.subject, instructions=row.instructions,
        wait_days=row.wait_days, skip_weekends=row.skip_weekends,
        created_at=row.created_at, updated_at=row.updated_at,
        created_by=row.created_by, updated_by=row.updated_by,
    )


def _cadence_template_out(row: CadenceTemplate, steps: list[CadenceStep] | None = None) -> crm_models.CadenceTemplateOut:
    ordered_steps = sorted(steps, key=lambda s: s.step_order) if steps is not None else []
    return crm_models.CadenceTemplateOut(
        id=row.id, name=row.name, description=row.description, is_active=row.is_active,
        steps=[_cadence_step_out(s) for s in ordered_steps],
        created_at=row.created_at, updated_at=row.updated_at,
        created_by=row.created_by, updated_by=row.updated_by,
    )


def _cadence_enrollment_out(row) -> crm_models.LeadCadenceEnrollmentOut:
    return crm_models.LeadCadenceEnrollmentOut(
        id=row.id, lead_id=row.lead_id, cadence_template_id=row.cadence_template_id,
        status=row.status, current_step_order=row.current_step_order,
        enrolled_at=row.enrolled_at, completed_at=row.completed_at, enrolled_by=row.enrolled_by,
        created_at=row.created_at, updated_at=row.updated_at,
        created_by=row.created_by, updated_by=row.updated_by,
    )


def _cadence_task_out(row, step: CadenceStep, lead: Lead) -> crm_models.CadenceTaskOut:
    return crm_models.CadenceTaskOut(
        id=row.id, enrollment_id=row.enrollment_id, cadence_step_id=row.cadence_step_id,
        lead_id=lead.id, step_type=step.step_type, subject=step.subject,
        due_date=row.due_date, status=row.status, completed_at=row.completed_at, notes=row.notes,
        auto_resolved=row.auto_resolved,
        created_at=row.created_at, updated_at=row.updated_at,
        created_by=row.created_by, updated_by=row.updated_by,
    )


def _compute_due_date(start: datetime, wait_days: int, skip_weekends: bool) -> date:
    """The one shared due-date calculation used by both
    enroll_lead_in_cadence() (the enrollment's first task) and
    complete_cadence_task()/advance_due_cadence_steps() (every task after) —
    see CadenceStep.skip_weekends.

    skip_weekends=False (the default) preserves the original calendar-day
    behavior verbatim: due = start + wait_days. skip_weekends=True instead
    walks forward one calendar day at a time, only counting Mon-Fri, until
    wait_days business days have been counted — Saturday/Sunday are never
    landed on as the result and never counted toward wait_days. wait_days=0
    always returns start's own date either way: a same-day step is due now,
    not bumped to the next business day just because "today" happens to
    fall on a weekend."""
    if not skip_weekends or wait_days <= 0:
        return (start + timedelta(days=wait_days)).date()
    current = start.date()
    remaining = wait_days
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Mon=0 .. Fri=4; Sat=5, Sun=6 don't count
            remaining -= 1
    return current


def _get_cadence_template_or_404(repo: CadenceTemplateRepository, tid) -> CadenceTemplate:
    row = repo.get(tid)
    if row is None:
        raise DomainError("CADENCE_TEMPLATE_NOT_FOUND", f"No cadence template '{tid}'.", 404)
    return row


def _get_cadence_step_or_404(repo: CadenceStepRepository, sid) -> CadenceStep:
    row = repo.get(sid)
    if row is None:
        raise DomainError("CADENCE_STEP_NOT_FOUND", f"No cadence step '{sid}'.", 404)
    return row


@handle_errors("list cadence templates")
def list_cadence_templates(user: CurrentUser, template_repo: CadenceTemplateRepository,
                           step_repo: CadenceStepRepository) -> list[crm_models.CadenceTemplateOut]:
    rows = sorted(template_repo.list(), key=lambda r: r.created_at, reverse=True)
    return [_cadence_template_out(t, step_repo.list_for_template(t.id)) for t in rows]


def _get_active_cadence_template(template_repo: CadenceTemplateRepository) -> CadenceTemplate | None:
    """Business rule: at most one CadenceTemplate is Active at a time (see
    _deactivate_other_cadence_templates()) — this is the one create_lead()
    auto-enrolls every new Lead into (see _auto_enroll_new_lead())."""
    for row in template_repo.list():
        if row.is_active:
            return row
    return None


def _deactivate_other_cadence_templates(user: CurrentUser, template_repo: CadenceTemplateRepository, keep_id) -> None:
    """Enforces "only ONE cadence template is Active at a time" — called
    whenever a template is created/updated as Active, so activating one
    template always deactivates whichever other one used to be Active. A
    template being deactivated mid-run doesn't touch Leads already enrolled
    in it (LeadCadenceEnrollment rows are independent of the template's
    current is_active flag)."""
    for row in template_repo.list():
        if row.is_active and row.id != keep_id:
            template_repo.update(row.id, is_active=False, updated_by=user.employee_id)


@handle_errors("create cadence template")
def create_cadence_template(user: CurrentUser, template_repo: CadenceTemplateRepository,
                            payload: crm_models.CadenceTemplateCreate) -> crm_models.CadenceTemplateOut:
    row = template_repo.create(
        name=payload.name, description=payload.description, is_active=True,
        created_by=user.employee_id, updated_by=user.employee_id,
    )
    _deactivate_other_cadence_templates(user, template_repo, row.id)
    return _cadence_template_out(row, [])


@handle_errors("get cadence template")
def get_cadence_template(user: CurrentUser, template_repo: CadenceTemplateRepository,
                         step_repo: CadenceStepRepository, tid) -> crm_models.CadenceTemplateOut:
    row = _get_cadence_template_or_404(template_repo, tid)
    return _cadence_template_out(row, step_repo.list_for_template(tid))


@handle_errors("update cadence template")
def update_cadence_template(user: CurrentUser, template_repo: CadenceTemplateRepository,
                            step_repo: CadenceStepRepository, tid,
                            payload: crm_models.CadenceTemplateUpdate) -> crm_models.CadenceTemplateOut:
    _get_cadence_template_or_404(template_repo, tid)
    changes = payload.model_dump(exclude_unset=True)
    changes["updated_by"] = user.employee_id
    updated = template_repo.update(tid, **changes)
    if changes.get("is_active"):
        _deactivate_other_cadence_templates(user, template_repo, tid)
    return _cadence_template_out(updated, step_repo.list_for_template(tid))


@handle_errors("add cadence step")
def add_cadence_step(user: CurrentUser, template_repo: CadenceTemplateRepository,
                     step_repo: CadenceStepRepository, tid,
                     payload: crm_models.CadenceStepCreate) -> crm_models.CadenceStepOut:
    _get_cadence_template_or_404(template_repo, tid)
    if any(s.step_order == payload.step_order for s in step_repo.list_for_template(tid)):
        raise DomainError(
            "CADENCE_STEP_ORDER_TAKEN",
            f"Step order {payload.step_order} is already used on this template.", 409)
    row = step_repo.create(
        cadence_template_id=tid, step_order=payload.step_order, step_type=payload.step_type,
        subject=payload.subject, instructions=payload.instructions, wait_days=payload.wait_days,
        skip_weekends=payload.skip_weekends,
        created_by=user.employee_id, updated_by=user.employee_id,
    )
    return _cadence_step_out(row)


@handle_errors("update cadence step")
def update_cadence_step(user: CurrentUser, step_repo: CadenceStepRepository, sid,
                        payload: crm_models.CadenceStepUpdate) -> crm_models.CadenceStepOut:
    row = _get_cadence_step_or_404(step_repo, sid)
    changes = payload.model_dump(exclude_unset=True)
    if "step_order" in changes and changes["step_order"] != row.step_order:
        siblings = step_repo.list_for_template(row.cadence_template_id)
        if any(s.id != sid and s.step_order == changes["step_order"] for s in siblings):
            raise DomainError(
                "CADENCE_STEP_ORDER_TAKEN",
                f"Step order {changes['step_order']} is already used on this template.", 409)
    changes["updated_by"] = user.employee_id
    updated = step_repo.update(sid, **changes)
    return _cadence_step_out(updated)


@handle_errors("delete cadence step")
def delete_cadence_step(user: CurrentUser, step_repo: CadenceStepRepository, sid) -> None:
    _get_cadence_step_or_404(step_repo, sid)
    step_repo.update(sid, updated_by=user.employee_id)
    step_repo.delete(sid)


def _create_enrollment_and_first_task(
    user_or_system_id: str | None, lead, template, steps: list[CadenceStep],
    enrollment_repo: LeadCadenceEnrollmentRepository, task_repo: CadenceTaskRepository,
    enrolled_by,
) -> crm_models.LeadCadenceEnrollmentDetailOut:
    """Shared by enroll_lead_in_cadence() (a rep's explicit choice) and
    _auto_enroll_new_lead() (system-driven, on create_lead()) — both have
    already validated template is-active/has-steps and that the lead has no
    other active enrollment by the time this runs."""
    now = _now()
    enrollment = enrollment_repo.create(
        lead_id=lead.id, cadence_template_id=template.id, status=LeadCadenceEnrollmentStatus.ACTIVE.value,
        current_step_order=steps[0].step_order, enrolled_at=now, completed_at=None,
        enrolled_by=enrolled_by, created_by=user_or_system_id, updated_by=user_or_system_id,
    )
    first_step = steps[0]
    task = task_repo.create(
        enrollment_id=enrollment.id, cadence_step_id=first_step.id,
        due_date=_compute_due_date(now, first_step.wait_days, first_step.skip_weekends),
        status=CadenceTaskStatus.PENDING.value, completed_at=None, notes=None, auto_resolved=False,
        created_by=user_or_system_id, updated_by=user_or_system_id,
    )
    return crm_models.LeadCadenceEnrollmentDetailOut(
        enrollment=_cadence_enrollment_out(enrollment),
        tasks=[_cadence_task_out(task, first_step, lead)],
    )


def _resolve_enrolled_by(user: CurrentUser, employees: EmployeeRepository):
    try:
        enrolled_by_uuid = UUID(str(user.employee_id))
        return enrolled_by_uuid if employees.get(enrolled_by_uuid) is not None else None
    except ValueError:
        return None


def _auto_enroll_new_lead(
    user: CurrentUser, lead, template_repo: CadenceTemplateRepository, step_repo: CadenceStepRepository,
    enrollment_repo: LeadCadenceEnrollmentRepository, task_repo: CadenceTaskRepository,
    employees: EmployeeRepository,
) -> None:
    """Called by create_lead() right after a new Lead is persisted (BRD
    Phase 2 #7): finds the single currently-Active cadence template (see
    _get_active_cadence_template()) and enrolls the brand-new lead into it,
    exactly like a rep manually enrolling it via enroll_lead_in_cadence() —
    without requiring the rep to pick anything. Best-effort only: no active
    template, or an active template with no steps yet, silently leaves the
    lead unenrolled (same "Not enrolled" state as before this feature) rather
    than failing the lead creation itself."""
    template = _get_active_cadence_template(template_repo)
    if template is None:
        return
    steps = sorted(step_repo.list_for_template(template.id), key=lambda s: s.step_order)
    if not steps:
        return
    _create_enrollment_and_first_task(
        user.employee_id, lead, template, steps, enrollment_repo, task_repo,
        _resolve_enrolled_by(user, employees),
    )


@handle_errors("enroll lead in cadence")
def enroll_lead_in_cadence(
    user: CurrentUser, lead_repo: LeadRepository, template_repo: CadenceTemplateRepository,
    step_repo: CadenceStepRepository, enrollment_repo: LeadCadenceEnrollmentRepository,
    task_repo: CadenceTaskRepository, employees: EmployeeRepository, lid,
    payload: crm_models.LeadCadenceEnrollRequest,
) -> crm_models.LeadCadenceEnrollmentDetailOut:
    lead = _get_lead_or_404(lead_repo, lid)
    _require_write_scope(user, lead, "Lead is outside your data scope.")
    template = _get_cadence_template_or_404(template_repo, payload.cadence_template_id)
    if not template.is_active:
        raise DomainError(
            "CADENCE_TEMPLATE_INACTIVE", "Cannot enroll into an inactive cadence template.", 422)
    if enrollment_repo.get_active_for_lead(lid) is not None:
        raise DomainError(
            "LEAD_ALREADY_IN_ACTIVE_CADENCE",
            "This lead already has an active cadence enrollment — cancel or complete it "
            "before enrolling in another.", 409)
    steps = sorted(step_repo.list_for_template(template.id), key=lambda s: s.step_order)
    if not steps:
        raise DomainError(
            "CADENCE_TEMPLATE_HAS_NO_STEPS", "Cannot enroll into a cadence template with no steps.", 422)

    return _create_enrollment_and_first_task(
        user.employee_id, lead, template, steps, enrollment_repo, task_repo,
        _resolve_enrolled_by(user, employees),
    )


@handle_errors("cancel cadence enrollment")
def cancel_lead_cadence_enrollment(
    user: CurrentUser, lead_repo: LeadRepository, enrollment_repo: LeadCadenceEnrollmentRepository,
    task_repo: CadenceTaskRepository, step_repo: CadenceStepRepository, lid,
) -> crm_models.LeadCadenceEnrollmentDetailOut:
    """The "cancel or complete it" the LEAD_ALREADY_IN_ACTIVE_CADENCE error
    on enroll_lead_in_cadence() has always promised, finally wired up —
    stops an active enrollment (e.g. enrolled into the wrong cadence)
    without having to walk every remaining step to completion. The current
    PENDING task is marked SKIPPED (there's no dedicated CANCELLED task
    status — SKIPPED already means "this step didn't happen") rather than
    left dangling; no further tasks are created."""
    lead = _get_lead_or_404(lead_repo, lid)
    _require_write_scope(user, lead, "Lead is outside your data scope.")
    enrollment = enrollment_repo.get_active_for_lead(lid)
    if enrollment is None:
        raise DomainError(
            "LEAD_HAS_NO_ACTIVE_CADENCE_ENROLLMENT", "This lead has no active cadence enrollment.", 404)

    now = _now()
    for task in task_repo.list_for_enrollment(enrollment.id):
        if task.status == CadenceTaskStatus.PENDING.value:
            task_repo.update(
                task.id, status=CadenceTaskStatus.SKIPPED.value, completed_at=now,
                notes=(task.notes or "Cancelled with the enrollment"), updated_by=user.employee_id,
            )
    updated_enrollment = enrollment_repo.update(
        enrollment.id, status=LeadCadenceEnrollmentStatus.CANCELLED.value, completed_at=now,
        updated_by=user.employee_id,
    )

    tasks = sorted(task_repo.list_for_enrollment(enrollment.id), key=lambda t: t.due_date)
    steps_by_id = {s.id: s for s in step_repo.list_for_template(enrollment.cadence_template_id)}
    return crm_models.LeadCadenceEnrollmentDetailOut(
        enrollment=_cadence_enrollment_out(updated_enrollment),
        tasks=[_cadence_task_out(t, steps_by_id[t.cadence_step_id], lead) for t in tasks],
    )


#: Step types whose DONE completion is a real, loggable outreach event —
#: auto-recorded as a Communication so it feeds Email/Call Insights without
#: a rep having to log it a second time (see activity_service.py). TASK/
#: OTHER/LINKEDIN/BREAK/FOLLOW_UP completions aren't email or call activity,
#: so they're left for the rep to log manually if they want it captured.
_CADENCE_ACTIVITY_STEP_TYPES = {CadenceStepType.CALL.value, CadenceStepType.EMAIL.value}


def _advance_past_step(
    enrollment, current_step: CadenceStep, step_repo: CadenceStepRepository,
    task_repo: CadenceTaskRepository, enrollment_repo: LeadCadenceEnrollmentRepository,
    now: datetime, actor: str | None,
) -> bool:
    """Shared "what happens after a step is resolved" tail — creates the
    next PENDING task (due date via _compute_due_date(), honoring
    next_step.skip_weekends) and advances current_step_order, or marks the
    enrollment COMPLETED when this was the last step. Used by both
    complete_cadence_task() (a rep's manual DONE/SKIPPED) and
    advance_due_cadence_steps() (the scheduler's BREAK auto-resolve /
    FOLLOW_UP auto-skip) so an enrollment advances identically either way.

    Only ever called after the triggering task's own PENDING -> terminal
    transition has already won its update_if() race (see both callers) —
    by the time this runs, this call is the only one advancing this
    enrollment for this step. Returns True iff this was the last step (the
    enrollment is now COMPLETED)."""
    all_steps = sorted(step_repo.list_for_template(current_step.cadence_template_id), key=lambda s: s.step_order)
    # A reopened SKIPPED task (see reopen_cadence_task()) is resolved a second
    # time after the enrollment already advanced past its step, so it must not
    # advance again: that would create a duplicate next-step task and rewind
    # current_step_order. Already advanced == the enrollment is no longer
    # ACTIVE (it completed/cancelled) or a task for a later step already exists.
    later_step_ids = {s.id for s in all_steps if s.step_order > current_step.step_order}
    if enrollment.status != LeadCadenceEnrollmentStatus.ACTIVE.value or any(
            t.cadence_step_id in later_step_ids for t in task_repo.list_for_enrollment(enrollment.id)):
        return False
    next_step = next((s for s in all_steps if s.step_order > current_step.step_order), None)
    if next_step is not None:
        task_repo.create(
            enrollment_id=enrollment.id, cadence_step_id=next_step.id,
            due_date=_compute_due_date(now, next_step.wait_days, next_step.skip_weekends),
            status=CadenceTaskStatus.PENDING.value, completed_at=None, notes=None, auto_resolved=False,
            created_by=actor, updated_by=actor,
        )
        enrollment_repo.update(enrollment.id, current_step_order=next_step.step_order, updated_by=actor)
        return False
    enrollment_repo.update(enrollment.id, status=LeadCadenceEnrollmentStatus.COMPLETED.value,
                           completed_at=now, updated_by=actor)
    return True


@handle_errors("complete cadence task")
def complete_cadence_task(
    user: CurrentUser, lead_repo: LeadRepository, enrollment_repo: LeadCadenceEnrollmentRepository,
    step_repo: CadenceStepRepository, task_repo: CadenceTaskRepository, task_id,
    payload: crm_models.CadenceTaskCompleteRequest,
    comm_repo: CommunicationRepository | None = None,
) -> crm_models.CadenceTaskOut:
    task = task_repo.get(task_id)
    if task is None:
        raise DomainError("CADENCE_TASK_NOT_FOUND", f"No cadence task '{task_id}'.", 404)
    if task.status != CadenceTaskStatus.PENDING.value:
        raise DomainError("CADENCE_TASK_NOT_PENDING", "Only a PENDING task can be completed.", 422)
    if payload.outcome_status not in (CadenceTaskStatus.DONE.value, CadenceTaskStatus.SKIPPED.value):
        raise DomainError(
            "CADENCE_TASK_OUTCOME_INVALID", "outcome_status must be DONE or SKIPPED.", 422)

    enrollment = enrollment_repo.get(task.enrollment_id)
    if enrollment is None:
        raise DomainError("CADENCE_ENROLLMENT_NOT_FOUND", "This task's enrollment no longer exists.", 404)
    lead = _get_lead_or_404(lead_repo, enrollment.lead_id)
    _require_write_scope(user, lead, "Lead is outside your data scope.")

    current_step = _get_cadence_step_or_404(step_repo, task.cadence_step_id)
    now = _now()
    # Atomic PENDING -> outcome_status transition (row-locked — see
    # CrudRepository.update_if in repositories/_base.py). This is what
    # actually closes the race with advance_due_cadence_steps() (the
    # scheduler) trying to auto-resolve/auto-skip this exact task at the
    # same moment: whichever of the two commits first wins and proceeds to
    # _advance_past_step() below; the loser gets None back here and reports
    # the same CADENCE_TASK_NOT_PENDING a sequential double-complete would
    # (the plain check above already covers the non-racing case; this is
    # the race-safe backstop for the concurrent one).
    updated_task = task_repo.update_if(
        task_id, expected={"status": CadenceTaskStatus.PENDING.value},
        status=payload.outcome_status, completed_at=now,
        # A reopened task still carries its earlier note — only replace it when a new one is given.
        notes=payload.notes if payload.notes is not None else task.notes,
        updated_by=user.employee_id,
    )
    if updated_task is None:
        raise DomainError("CADENCE_TASK_NOT_PENDING", "Only a PENDING task can be completed.", 422)

    if (comm_repo is not None and payload.outcome_status == CadenceTaskStatus.DONE.value
            and current_step.step_type in _CADENCE_ACTIVITY_STEP_TYPES):
        comm_repo.create(
            lead_id=lead.id, account_id=None, agreement_id=None,
            direction="OUTBOUND", channel=current_step.step_type, subject=current_step.subject,
            occurred_at=now, source="CADENCE", logged_by_employee_id=None,
            created_by=user.employee_id, updated_by=user.employee_id,
        )

    _advance_past_step(enrollment, current_step, step_repo, task_repo, enrollment_repo, now, user.employee_id)
    return _cadence_task_out(updated_task, current_step, lead)


@handle_errors("reopen cadence task")
def reopen_cadence_task(
    user: CurrentUser, lead_repo: LeadRepository, enrollment_repo: LeadCadenceEnrollmentRepository,
    step_repo: CadenceStepRepository, task_repo: CadenceTaskRepository, task_id,
) -> crm_models.CadenceTaskOut:
    """SKIPPED -> PENDING on the SAME task row, so a skipped step can be
    worked again. Deliberately does nothing else: no new task is created, no
    other task or the enrollment is touched, and the due date, subject, notes
    and original resolution timestamp (completed_at, overwritten only when the
    task is resolved again) are kept. Resolving the reopened task afterwards
    goes through complete_cadence_task() like any PENDING task, and
    _advance_past_step() keeps that from advancing the cadence a second time.
    A CANCELLED enrollment's tasks can't be reopened — that cadence was
    stopped on purpose."""
    task = task_repo.get(task_id)
    if task is None:
        raise DomainError("CADENCE_TASK_NOT_FOUND", f"No cadence task '{task_id}'.", 404)
    if task.status != CadenceTaskStatus.SKIPPED.value:
        raise DomainError("CADENCE_TASK_NOT_SKIPPED", "Only a SKIPPED task can be reopened.", 422)
    enrollment = enrollment_repo.get(task.enrollment_id)
    if enrollment is None:
        raise DomainError("CADENCE_ENROLLMENT_NOT_FOUND", "This task's enrollment no longer exists.", 404)
    if enrollment.status == LeadCadenceEnrollmentStatus.CANCELLED.value:
        raise DomainError(
            "CADENCE_ENROLLMENT_CANCELLED", "A task of a cancelled cadence can't be reopened.", 422)
    lead = _get_lead_or_404(lead_repo, enrollment.lead_id)
    _require_write_scope(user, lead, "Lead is outside your data scope.")
    step = _get_cadence_step_or_404(step_repo, task.cadence_step_id)

    # Race-safe like complete_cadence_task(): only one concurrent reopen wins.
    updated_task = task_repo.update_if(
        task_id, expected={"status": CadenceTaskStatus.SKIPPED.value},
        status=CadenceTaskStatus.PENDING.value, auto_resolved=False, updated_by=user.employee_id,
    )
    if updated_task is None:
        raise DomainError("CADENCE_TASK_NOT_SKIPPED", "Only a SKIPPED task can be reopened.", 422)
    return _cadence_task_out(updated_task, step, lead)


def _previous_activity_cutoff(
    enrollment, follow_up_step: CadenceStep, step_repo: CadenceStepRepository, task_repo: CadenceTaskRepository,
) -> datetime:
    """The point in time advance_due_cadence_steps() measures a FOLLOW_UP
    step's "has the lead replied since [the relevant previous activity]"
    condition from — the completion of this enrollment's task for the
    immediately preceding step in the same template, or (a FOLLOW_UP with no
    earlier step, an edge case) the enrollment's own enrolled_at."""
    all_steps = sorted(step_repo.list_for_template(follow_up_step.cadence_template_id), key=lambda s: s.step_order)
    previous_steps = [s for s in all_steps if s.step_order < follow_up_step.step_order]
    if not previous_steps:
        return enrollment.enrolled_at
    previous_step = previous_steps[-1]
    previous_tasks = [t for t in task_repo.list_for_enrollment(enrollment.id)
                      if t.cadence_step_id == previous_step.id]
    if not previous_tasks or previous_tasks[0].completed_at is None:
        return enrollment.enrolled_at
    return previous_tasks[0].completed_at


def _lead_has_replied_since(comm_repo: CommunicationRepository, lead_id, cutoff: datetime) -> bool:
    """A reply is either an INBOUND Communication logged after `cutoff`
    (e.g. via /email-intake/poll) or an OUTBOUND one whose replied_at (see
    activity_service.mark_communication_replied()) falls after `cutoff`."""
    for comm in comm_repo.list_for_lead(lead_id):
        if comm.direction == "INBOUND" and comm.occurred_at >= cutoff:
            return True
        if comm.replied_at is not None and comm.replied_at >= cutoff:
            return True
    return False


@handle_errors("advance due cadence steps")
def advance_due_cadence_steps(
    enrollment_repo: LeadCadenceEnrollmentRepository, step_repo: CadenceStepRepository,
    task_repo: CadenceTaskRepository, comm_repo: CommunicationRepository,
) -> crm_models.CadenceSchedulerRunOut:
    """POST /cadence/advance-due-steps (see require_cadence_scheduler_secret)
    — the scheduler tick that makes BREAK/FOLLOW_UP steps self-driving
    instead of waiting on a rep:

    - a due BREAK task is auto-marked DONE (auto_resolved=True) and the
      enrollment advances — no Communication is logged (a BREAK is a pure
      wait, not outreach);
    - a due FOLLOW_UP task is auto-marked SKIPPED (auto_resolved=True) and
      the enrollment advances ONLY if the lead has replied since the
      previous step's activity (see _previous_activity_cutoff() /
      _lead_has_replied_since()); otherwise it's left PENDING for a rep to
      work like any other real outreach step.

    Only ACTIVE enrollments are scanned (list_active(), filtered at the DB
    level rather than loading every enrollment ever created), and only
    pending tasks that are actually due (due_date <= today) are acted on.

    Every state transition goes through CadenceTaskRepository.update_if
    (row-locked, conditional on the task still being PENDING) — see
    complete_cadence_task()'s docstring on the same mechanism. That's what
    makes this idempotent under both re-running concurrently/repeatedly and
    racing a rep's manual completion of the very same task: whichever
    caller's update_if() commits first is the only one that creates a next
    task or advances the enrollment; every other caller (a second scheduler
    run, or complete_cadence_task()) sees the task is no longer PENDING and
    does nothing further for it."""
    today = _now().date()
    enrollments_by_id = {e.id: e for e in enrollment_repo.list_active()}
    tally = crm_models.CadenceSchedulerRunOut(
        breaks_resolved=0, follow_ups_skipped=0, follow_ups_left_pending=0, enrollments_completed=0)
    if not enrollments_by_id:
        return tally

    for task in task_repo.list_pending():
        enrollment = enrollments_by_id.get(task.enrollment_id)
        if enrollment is None or task.due_date > today:
            continue
        step = step_repo.get(task.cadence_step_id)
        if step is None:
            continue
        now = _now()

        if step.step_type == CadenceStepType.BREAK.value:
            updated = task_repo.update_if(
                task.id, expected={"status": CadenceTaskStatus.PENDING.value},
                status=CadenceTaskStatus.DONE.value, completed_at=now, auto_resolved=True,
                updated_by=None,
            )
            if updated is None:
                continue  # a concurrent run or a manual completion already handled it
            tally.breaks_resolved += 1
            if _advance_past_step(enrollment, step, step_repo, task_repo, enrollment_repo, now, None):
                tally.enrollments_completed += 1

        elif step.step_type == CadenceStepType.FOLLOW_UP.value:
            cutoff = _previous_activity_cutoff(enrollment, step, step_repo, task_repo)
            if not _lead_has_replied_since(comm_repo, enrollment.lead_id, cutoff):
                tally.follow_ups_left_pending += 1
                continue
            updated = task_repo.update_if(
                task.id, expected={"status": CadenceTaskStatus.PENDING.value},
                status=CadenceTaskStatus.SKIPPED.value, completed_at=now, auto_resolved=True,
                notes="Auto-skipped: the lead replied before this follow-up came due.",
                updated_by=None,
            )
            if updated is None:
                continue  # a concurrent run or a manual completion already handled it
            tally.follow_ups_skipped += 1
            if _advance_past_step(enrollment, step, step_repo, task_repo, enrollment_repo, now, None):
                tally.enrollments_completed += 1

    return tally


@handle_errors("get lead cadence detail")
def get_lead_cadence_detail(
    user: CurrentUser, lead_repo: LeadRepository, enrollment_repo: LeadCadenceEnrollmentRepository,
    task_repo: CadenceTaskRepository, step_repo: CadenceStepRepository, lid,
) -> crm_models.LeadCadenceEnrollmentDetailOut:
    lead = _get_lead_or_404(lead_repo, lid)
    _require_read_scope(user, lead, "Lead is outside your data scope.")
    enrollments = enrollment_repo.list_for_lead(lid)
    if not enrollments:
        raise DomainError(
            "LEAD_HAS_NO_CADENCE_ENROLLMENT", "This lead has never been enrolled in a cadence.", 404)
    active = next((e for e in enrollments if e.status == LeadCadenceEnrollmentStatus.ACTIVE.value), None)
    enrollment = active or max(enrollments, key=lambda e: e.enrolled_at)

    tasks = sorted(task_repo.list_for_enrollment(enrollment.id), key=lambda t: t.due_date)
    steps_by_id = {s.id: s for s in step_repo.list_for_template(enrollment.cadence_template_id)}
    return crm_models.LeadCadenceEnrollmentDetailOut(
        enrollment=_cadence_enrollment_out(enrollment),
        tasks=[_cadence_task_out(t, steps_by_id[t.cadence_step_id], lead) for t in tasks],
    )


@handle_errors("list my cadence tasks")
def list_my_cadence_tasks(
    user: CurrentUser, lead_repo: LeadRepository, enrollment_repo: LeadCadenceEnrollmentRepository,
    task_repo: CadenceTaskRepository, step_repo: CadenceStepRepository,
) -> list[crm_models.CadenceTaskOut]:
    my_tasks = []
    for task in task_repo.list_pending():
        enrollment = enrollment_repo.get(task.enrollment_id)
        if enrollment is None:
            continue
        lead = lead_repo.get(enrollment.lead_id)
        if lead is None or not _owned_by(user, lead):
            continue
        step = step_repo.get(task.cadence_step_id)
        if step is None:
            continue
        my_tasks.append(_cadence_task_out(task, step, lead))
    my_tasks.sort(key=lambda t: t.due_date)
    return my_tasks


# --- AI-assisted email drafting & call prep (BRD §5.6/§5.7) -----------------
# llm_client is injected the same way a repository is (Depends(get_llm_client)
# — see server/crm_routes.py) so tests can substitute a fake via FastAPI's
# app.dependency_overrides instead of hitting the real network.


def _parse_json_response(raw: str, required_keys: set[str]) -> dict:
    """Models are asked to return bare JSON but sometimes wrap it in a
    markdown code fence anyway — strip that before parsing rather than
    failing a well-formed response over formatting."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text[:4].lower() == "json":
            text = text[4:]
        text = text.strip()
    try:
        # strict=False: Cohere sometimes emits raw control characters (e.g. an
        # actual newline) inside a JSON string value rather than escaping them
        # — reject only genuinely malformed JSON, not that.
        parsed = json.loads(text, strict=False)
    except (json.JSONDecodeError, ValueError) as exc:
        raise DomainError(
            "AI_RESPONSE_INVALID", f"The AI provider's response wasn't valid JSON: {exc}", 502) from exc
    if not isinstance(parsed, dict) or not required_keys.issubset(parsed.keys()):
        raise DomainError(
            "AI_RESPONSE_INVALID",
            f"The AI provider's response was missing expected fields: {sorted(required_keys)}.", 502)
    return parsed


def _communication_timeline_summary(comm_repo: CommunicationRepository, lid) -> str | None:
    """Prior touches on this lead, oldest first — the only continuity the AI
    drafting endpoints have to work with, since Communication only persists
    subject/channel/direction/timing, never the actual email body or call
    notes (those are ephemeral once sent/logged). Still enough for the model
    to tell "this is a first touch" from "this is the fourth follow-up and
    they've never replied" rather than writing every draft as a cold open."""
    history = sorted(comm_repo.list_for_lead(lid), key=lambda c: c.occurred_at)
    if not history:
        return None
    lines = []
    for c in history:
        who = "them -> us" if c.direction == "INBOUND" else "us -> them"
        when = c.occurred_at.date().isoformat()
        subject = f' "{c.subject}"' if c.subject else ""
        reply_note = " (they replied)" if c.replied_at else ""
        lines.append(f"- {when} [{c.channel}, {who}]{subject}{reply_note}")
    return "\n".join(lines)


def _format_product_catalog(products: list) -> str:
    """Renders the active product catalog for an AI drafting prompt. Kept as
    one helper so email-draft/call-prep/any future drafting endpoint present
    the catalog identically."""
    if not products:
        return "(No products are configured yet — write a generic but still well-researched pitch.)"
    lines = []
    for p in products:
        fit = f" — best fit: {p.target_industry}" if p.target_industry else ""
        lines.append(f"- {p.name}: {p.description}{fit}")
    return "\n".join(lines)


@handle_errors("generate email draft")
def generate_email_draft(user: CurrentUser, lead_repo: LeadRepository, comm_repo: CommunicationRepository,
                         products_repo: ProductRepository, llm_client: LLMClient,
                         lid) -> crm_models.EmailDraftOut:
    lead = _get_lead_or_404(lead_repo, lid)
    _require_read_scope(user, lead, "Lead is outside your data scope.")

    # AI-2: ground the draft in what's actually gotten a reply for this
    # industry before — a lightweight, honest proxy for "historical
    # conversion data" (a full analytics pipeline is a separate project).
    grounding_subjects: list[str] = []
    if lead.industry:
        same_industry_ids = {
            other.id for other in lead_repo.list() if (other.industry or "").lower() == lead.industry.lower()}
        for c in comm_repo.list():
            if (c.channel == LeadCommunicationChannel.EMAIL.value and c.direction == "OUTBOUND"
                    and c.replied_at is not None and c.lead_id in same_industry_ids and c.subject):
                grounding_subjects.append(c.subject)
    grounding_subjects = grounding_subjects[:5]

    contact_name = _lead_full_name(lead) or "there"
    catalog = _format_product_catalog(products_repo.list_active())
    timeline = _communication_timeline_summary(comm_repo, lid)
    system_prompt = (
        'You are a B2B sales development rep writing a short, personalized outreach email — a cold open '
        "if this is the first touch, or an appropriate follow-up (referencing, not repeating, what's "
        "already been sent) if a prior touch history is given below. Pick whichever of OUR products/"
        "services below is the best fit for the recipient's company/industry, and write the email around "
        "that specific fit (not a generic pitch). If you genuinely recognize the company, you may "
        "reference one real, well-known fact about it — but never invent specifics (funding, headcount, "
        'news) you are not confident are true. Respond with ONLY a JSON object of the shape {"subject": '
        '"...", "body": "...", "matched_products": ["...", ...]} and nothing else. matched_products lists '
        "the name(s) of the product(s) from our catalog the email is built around (empty list if none "
        "fit).\n\n"
        f"Our products/services:\n{catalog}")
    user_prompt = (
        f"Recipient: {contact_name}, title: {lead.title or 'unknown'}, at {lead.company_name} "
        f"(industry: {lead.industry or 'unknown'}"
        f"{f', website: {lead.website}' if lead.website else ''}).\n"
        "Write a concise (under 130 words) email that connects their likely needs to the matched "
        "product's value. Tone: professional, warm, not salesy.")
    if timeline:
        user_prompt += f"\n\nPrior touches on this lead, oldest first:\n{timeline}"
    if grounding_subjects:
        user_prompt += (
            "\nSubject lines that have previously gotten a reply from leads in this industry "
            "(for inspiration only, don't copy verbatim): " + "; ".join(grounding_subjects))

    raw = llm_client.complete(system_prompt, user_prompt)
    parsed = _parse_json_response(raw, {"subject", "body"})
    return crm_models.EmailDraftOut(
        subject=str(parsed["subject"]), body=str(parsed["body"]),
        model=get_settings().COHERE_MODEL, grounded_in_replies=len(grounding_subjects),
        matched_products=[str(p) for p in parsed.get("matched_products", [])],
    )


@handle_errors("generate call prep")
def generate_call_prep(user: CurrentUser, lead_repo: LeadRepository, comm_repo: CommunicationRepository,
                       products_repo: ProductRepository, llm_client: LLMClient, lid) -> crm_models.CallPrepOut:
    lead = _get_lead_or_404(lead_repo, lid)
    _require_read_scope(user, lead, "Lead is outside your data scope.")

    contact_name = _lead_full_name(lead) or "the contact"
    catalog = _format_product_catalog(products_repo.list_active())
    timeline = _communication_timeline_summary(comm_repo, lid)
    system_prompt = (
        'You are a sales coach preparing a rep for an outbound call — their first with this lead if no '
        "prior touch history is given below, otherwise a follow-up call that should pick up from where "
        "things actually stand rather than re-introducing the pitch from scratch. Pick whichever of OUR "
        "products/services below is the best fit for this company/industry, and build the prep around "
        "that fit. If you genuinely recognize the company, you may reference one real, well-known fact "
        "about it — but never invent specifics (funding, headcount, news) you are not confident are "
        'true. Respond with ONLY a JSON object of the shape {"talking_points": '
        '["...", ...], "likely_objections": ["...", ...], "opening_line": "...", "matched_products": '
        '["...", ...]} and nothing else. matched_products lists the name(s) of the product(s) from our '
        "catalog the prep is built around (empty list if none fit).\n\n"
        f"Our products/services:\n{catalog}")
    user_prompt = (
        f"Prep a call with {contact_name}, title: {lead.title or 'unknown'}, at {lead.company_name} "
        f"(industry: {lead.industry or 'unknown'}, rating: {lead.rating or 'unrated'}"
        f"{f', website: {lead.website}' if lead.website else ''}).\n"
        "Give 3-5 talking points that connect this persona/industry to the matched product's value, "
        "2-3 likely objections with how to counter them, and a short suggested opening line.")
    if timeline:
        user_prompt += f"\n\nPrior touches on this lead, oldest first:\n{timeline}"

    raw = llm_client.complete(system_prompt, user_prompt)
    parsed = _parse_json_response(raw, {"talking_points", "likely_objections", "opening_line"})
    return crm_models.CallPrepOut(
        talking_points=[str(p) for p in parsed["talking_points"]],
        likely_objections=[str(o) for o in parsed["likely_objections"]],
        opening_line=str(parsed["opening_line"]), model=get_settings().COHERE_MODEL,
        matched_products=[str(p) for p in parsed.get("matched_products", [])],
    )


@handle_errors("generate web enrichment")
def generate_web_lead_enrichment(
    user: CurrentUser, lead_repo: LeadRepository, rules_repo: LeadScoringRuleRepository,
    llm_client: LLMClient, lid,
) -> crm_models.LeadWebEnrichmentOut:
    """BRD SC-2: score fit/intent using signals (funding, hiring, growth)
    beyond only in-system behavior.

    No live web search: Cohere retired their hosted web-search connector
    (see services/llm_client.py) and adding a separate search provider was
    explicitly deferred, so this reasons from the model's own knowledge of
    the company under a strict "say unknown rather than invent" instruction
    — a best-effort signal, not a verified news feed. The resulting
    score_points is persisted as Lead.web_enrichment_points and combined
    with the rule-based score into lead_score (see _total_lead_score()) —
    re-running this later replaces the web component only, never the
    rule-based one."""
    lead = _get_lead_or_404(lead_repo, lid)
    _require_write_scope(user, lead, "Lead is outside your data scope.")

    system_prompt = (
        'You are a B2B sales research assistant. Based only on what you already, confidently know about '
        "the given company (do not guess or invent) — funding rounds, hiring/growth activity, or "
        'product/tech announcements — respond with ONLY a JSON object of the shape {"funding_signal": '
        'bool, "hiring_signal": bool, "growth_signal": bool, "headlines": ["...", ...], "score_points": '
        'int, "summary": "..."} and nothing else. score_points is 0-30 and reflects how strong a '
        "buying-intent signal your findings are (0 = you don't have confident, specific knowledge of "
        "this company, or nothing notable comes to mind, 30 = you're confident about major recent "
        "funding/expansion). If you aren't confident about specifics, return all signals false, an "
        "empty headlines list, score_points 0, and a summary saying so — never invent news.")
    user_prompt = f"Company: {lead.company_name}"
    if lead.industry:
        user_prompt += f" (industry: {lead.industry})"
    if lead.website:
        user_prompt += f", website: {lead.website}"

    text = llm_client.complete(system_prompt, user_prompt)
    parsed = _parse_json_response(
        text, {"funding_signal", "hiring_signal", "growth_signal", "headlines", "score_points", "summary"})

    try:
        raw_points = int(parsed["score_points"])
    except (TypeError, ValueError):
        raw_points = 0
    score_points = max(0, min(30, raw_points))  # clamp to the range the prompt asked for

    now = _now()
    enriched = lead_repo.update(
        lid, web_enrichment_points=score_points, web_enrichment_summary=str(parsed["summary"])[:2000],
        web_enrichment_at=now, updated_by=user.employee_id,
    )
    effective = {f: getattr(enriched, f) for f in _SCORABLE_LEAD_FIELDS}
    rule_score = _compute_lead_score(effective, rules_repo.list_active())
    final = lead_repo.update(
        lid, lead_score=_total_lead_score(rule_score, score_points, enriched.signal_points),
        updated_by=user.employee_id)

    return crm_models.LeadWebEnrichmentOut(
        funding_signal=bool(parsed["funding_signal"]), hiring_signal=bool(parsed["hiring_signal"]),
        growth_signal=bool(parsed["growth_signal"]), headlines=[str(h) for h in parsed["headlines"]][:5],
        score_points=score_points, summary=str(parsed["summary"]),
        lead_score=final.lead_score, model=get_settings().COHERE_MODEL,
    )


# --- Pulse: signal sourcing, Radar worklist, next-best-action ---------------
# Pulse is the intelligence layer on top of the Lead pipeline above: verified
# Signal rows (crm_models.Signal) feed a decayed, capped score component
# (Lead.signal_points - combined into lead_score via _total_lead_score(),
# same treatment as web_enrichment_points) and a grounded Next-Best-Action.
# Unlike generate_web_lead_enrichment() above, nothing here asks an LLM to
# recall facts about a company from memory - every Signal is sourced data
# (mock adapters today, see _MOCK_SIGNAL_CATALOG; a real feed later is one
# more source list, no change to the scoring/Radar/NBA functions below), and
# the NBA prompt is grounded strictly in a lead's own signals/score/fields.

#: Radar/Signals practice taxonomy - kept as a plain list (not a lookup
#: table) since it's a small, code-level vocabulary shared with the mock
#: signal catalog below, not admin-customizable reference data.
PULSE_PRACTICES = ["Data & AI", "Cloud & Platform", "Digital Engineering", "Cybersecurity", "Advisory"]

_SIGNAL_TYPE_LABEL: dict[str, str] = {
    SignalType.HIRING.value: "Hiring",
    SignalType.RFP_TENDER.value: "RFP / Tender",
    SignalType.TECH_STACK.value: "Tech stack",
    SignalType.BUYER_INTENT.value: "Buyer intent",
    SignalType.LEADERSHIP_MOVE.value: "Leadership move",
    SignalType.FUNDING_MA.value: "Funding / M&A",
    SignalType.FILING_EARNINGS.value: "Filing / Earnings",
    SignalType.WEB_EVENT.value: "Web event",
}

#: A signal's raw `strength` (0..1) decays linearly to 0 over this many days
#: - an old signal should stop moving the score without anyone having to
#: touch it (see _signal_decay_points()).
_SIGNAL_DECAY_DAYS = 90
#: Ceiling on one signal's own decayed contribution.
_MAX_SIGNAL_POINTS_PER_SIGNAL = 40
#: Ceiling on a lead's *summed* signal_points across every one of its
#: signals - several fresh signals shouldn't be able to blow the composite
#: score out past what a genuinely hot lead looks like.
_MAX_LEAD_SIGNAL_POINTS = 60

#: Mock sourcing catalog (BRD's "signal sourcing, mock adapters now, real
#: feeds later") - a fixed set of synthetic-but-plausible external signals
#: keyed by the source that would produce them in a real integration
#: (LinkedIn Jobs, SAM.gov, BuiltWith, Crunchbase, SEC EDGAR, ...).
#: ingest_signals() is what turns this into real Signal rows + Leads;
#: nothing here is itself persisted or returned directly.
_MOCK_SIGNAL_CATALOG: list[dict] = [
    {"company_name": "Solvane Health", "type": SignalType.HIRING.value, "source": "LinkedIn Jobs",
     "summary": "Posted 6 new Data Engineer and MLOps roles this month.", "strength": 0.80,
     "practice_hint": "Data & AI", "age_days": 3, "url": None},
    {"company_name": "Solvane Health", "type": SignalType.BUYER_INTENT.value, "source": "BuiltWith",
     "summary": "Added Snowflake and Databricks to their public tech stack this quarter.", "strength": 0.70,
     "practice_hint": "Data & AI", "age_days": 10, "url": None},
    {"company_name": "Northfall Logistics", "type": SignalType.RFP_TENDER.value, "source": "SAM.gov",
     "summary": "Issued an RFP for cloud migration and platform modernization.", "strength": 0.90,
     "practice_hint": "Cloud & Platform", "age_days": 2, "url": None},
    {"company_name": "Northfall Logistics", "type": SignalType.TECH_STACK.value, "source": "BuiltWith",
     "summary": "Migrated primary workloads from on-prem VMware to AWS.", "strength": 0.60,
     "practice_hint": "Cloud & Platform", "age_days": 20, "url": None},
    {"company_name": "Ironbridge Robotics", "type": SignalType.FUNDING_MA.value, "source": "Crunchbase",
     "summary": "Closed a $40M Series C led by a growth-stage fund.", "strength": 0.85,
     "practice_hint": "Digital Engineering", "age_days": 5, "url": None},
    {"company_name": "Ironbridge Robotics", "type": SignalType.LEADERSHIP_MOVE.value, "source": "PR Newswire",
     "summary": "Appointed a new VP of Engineering hired from a competitor.", "strength": 0.60,
     "practice_hint": "Digital Engineering", "age_days": 15, "url": None},
    {"company_name": "Halcyon Financial", "type": SignalType.FILING_EARNINGS.value, "source": "SEC EDGAR",
     "summary": "10-Q flagged increased security/compliance spend for next fiscal year.", "strength": 0.75,
     "practice_hint": "Cybersecurity", "age_days": 8, "url": None},
    {"company_name": "Halcyon Financial", "type": SignalType.RFP_TENDER.value, "source": "SAM.gov",
     "summary": "Issued an RFP for a SOC 2 readiness and penetration-testing engagement.", "strength": 0.90,
     "practice_hint": "Cybersecurity", "age_days": 1, "url": None},
    {"company_name": "Cascadia Retail Group", "type": SignalType.HIRING.value, "source": "LinkedIn Jobs",
     "summary": "Hiring a Director of Digital Transformation.", "strength": 0.65,
     "practice_hint": "Advisory", "age_days": 25, "url": None},
    {"company_name": "Cascadia Retail Group", "type": SignalType.WEB_EVENT.value, "source": "Company Blog",
     "summary": "Published a post announcing a company-wide digital roadmap.", "strength": 0.55,
     "practice_hint": "Advisory", "age_days": 40, "url": None},
    {"company_name": "Vermilion Manufacturing", "type": SignalType.TECH_STACK.value, "source": "BuiltWith",
     "summary": "Added Kubernetes and Terraform to their public job postings' stack list.", "strength": 0.60,
     "practice_hint": "Cloud & Platform", "age_days": 12, "url": None},
    {"company_name": "Driftwood Media", "type": SignalType.BUYER_INTENT.value, "source": "Crunchbase",
     "summary": "Profile viewed/followed by 3 competing vendors this week.", "strength": 0.50,
     "practice_hint": "Data & AI", "age_days": 4, "url": None},
]


def _signal_decay_points(signal: Signal, now: datetime) -> int:
    """A signal's decayed, current contribution to its lead's score - never
    stored (see crm_models.Signal's docstring), so a signal quietly ages out
    of the score without any write happening to it."""
    age_days = max(0, (now - signal.captured_at).days)
    if age_days >= _SIGNAL_DECAY_DAYS:
        return 0
    remaining = 1 - (age_days / _SIGNAL_DECAY_DAYS)
    return round(float(signal.strength) * _MAX_SIGNAL_POINTS_PER_SIGNAL * remaining)


def _grade_for_score(score: int) -> str:
    """A/B/C/D band for Radar's grade column - display-only, never stored."""
    if score >= 70:
        return "A"
    if score >= 45:
        return "B"
    if score >= 20:
        return "C"
    return "D"


def _age_days(then: datetime, now: datetime) -> int:
    return max(0, (now - then).days)


def _age_label(days: int) -> str:
    if days <= 0:
        return "today"
    if days == 1:
        return "1 day ago"
    if days < 30:
        return f"{days} days ago"
    months = days // 30
    return "1 month ago" if months == 1 else f"{months} months ago"


def _signal_out(row: Signal, now: datetime) -> crm_models.SignalOut:
    return crm_models.SignalOut(
        id=row.id, lead_id=row.lead_id, company_name=row.company_name, type=row.type,
        source=row.source, summary=row.summary, strength=float(row.strength),
        practice_hint=row.practice_hint, url=row.url, captured_at=row.captured_at,
        score_points=_signal_decay_points(row, now),
    )


def _recompute_lead_pulse(
    user: CurrentUser, lead_repo: LeadRepository, rules_repo: LeadScoringRuleRepository,
    signal_repo: SignalRepository, lead: Lead, now: datetime,
) -> Lead:
    """Recomputes signal_points from this lead's current signals (decayed,
    capped) and folds it back into lead_score alongside the rule-based and
    web-enrichment components - called whenever ingest_signals() sources
    something new for this lead. Never touches web_enrichment_points: that
    component is only ever written by generate_web_lead_enrichment()."""
    points = min(
        _MAX_LEAD_SIGNAL_POINTS,
        sum(_signal_decay_points(s, now) for s in signal_repo.list_for_lead(lead.id)),
    )
    scoring_fields = {f: getattr(lead, f) for f in _SCORABLE_LEAD_FIELDS}
    rule_score = _compute_lead_score(scoring_fields, rules_repo.list_active())
    return lead_repo.update(
        lead.id, signal_points=points,
        lead_score=_total_lead_score(rule_score, lead.web_enrichment_points, points),
        updated_by=user.employee_id,
    )


@handle_errors("list lead signals")
def list_lead_signals(
    user: CurrentUser, lead_repo: LeadRepository, signal_repo: SignalRepository, lid,
) -> list[crm_models.SignalOut]:
    lead = _get_lead_or_404(lead_repo, lid)
    _require_read_scope(user, lead, "Lead is outside your data scope.")
    now = _now()
    rows = sorted(signal_repo.list_for_lead(lid), key=lambda s: s.captured_at, reverse=True)
    return [_signal_out(s, now) for s in rows]


@handle_errors("ingest signals")
def ingest_signals(
    user: CurrentUser, lead_repo: LeadRepository, signal_repo: SignalRepository,
    rules_repo: LeadScoringRuleRepository, since_days: int = 30,
) -> crm_models.SignalIngestResult:
    """Runs the mock sourcing catalog (swap for real feeds later - see the
    module docstring above), creating any Signal rows this run hasn't
    already ingested (deduped via SignalRepository.exists()), creating a
    Lead for any sourced company that doesn't already have one (matched
    case-insensitively on company_name - see LeadRepository.
    find_by_company_name()), and rescoring every Lead this run touched."""
    now = _now()
    sources_run: set[str] = set()
    signals_ingested = 0
    leads_created = 0
    leads_updated = 0
    touched_lead_ids: set = set()

    for entry in _MOCK_SIGNAL_CATALOG:
        if entry["age_days"] > since_days:
            continue
        sources_run.add(entry["source"])
        if signal_repo.exists(entry["company_name"], entry["type"], entry["source"]):
            continue
        captured_at = now - timedelta(days=entry["age_days"])

        lead = lead_repo.find_by_company_name(entry["company_name"])
        if lead is None:
            lead = lead_repo.create(
                company_name=entry["company_name"], last_name="Unknown",
                source="Pulse", status=LeadStatus.NEW.value, lead_score=0,
                created_by=user.employee_id, updated_by=user.employee_id,
            )
            leads_created += 1
        else:
            leads_updated += 1

        signal_repo.create(
            lead_id=lead.id, company_name=entry["company_name"], type=entry["type"],
            source=entry["source"], summary=entry["summary"], strength=entry["strength"],
            practice_hint=entry["practice_hint"], url=entry["url"], captured_at=captured_at,
            created_by=user.employee_id, updated_by=user.employee_id,
        )
        signals_ingested += 1
        touched_lead_ids.add(lead.id)

    rescored = 0
    for lead_id in touched_lead_ids:
        lead = lead_repo.get(lead_id)
        if lead is not None:
            _recompute_lead_pulse(user, lead_repo, rules_repo, signal_repo, lead, now)
            rescored += 1

    return crm_models.SignalIngestResult(
        sources_run=sorted(sources_run), signals_ingested=signals_ingested,
        leads_created=leads_created, leads_updated=leads_updated, rescored=rescored,
    )


@handle_errors("get radar")
def get_radar(
    user: CurrentUser, lead_repo: LeadRepository, signal_repo: SignalRepository, *,
    mine: bool = False, practice: str | None = None, min_score: int = 0,
) -> list[crm_models.RadarRow]:
    """The prioritized worklist: every in-scope, still-active lead that has
    at least one signal, ranked by composite score. A lead with no signals
    yet has nothing "why now" to say, so it stays off Radar (still visible
    in the plain Leads list) until a sourcing run finds something."""
    now = _now()
    _TERMINAL = {LeadStatus.CONVERTED.value, LeadStatus.UNQUALIFIED.value, LeadStatus.DISQUALIFIED.value}
    owd_repo = get_org_wide_default_repository()
    leads = [lead for lead in lead_repo.list() if _in_read_scope(user, lead, owd_repo) and lead.status not in _TERMINAL]
    if mine:
        leads = [lead for lead in leads if _owned_by(user, lead)]

    rows: list[crm_models.RadarRow] = []
    for lead in leads:
        if lead.lead_score < min_score:
            continue
        signals = signal_repo.list_for_lead(lead.id)
        if not signals:
            continue
        ranked_signals = sorted(
            signals, key=lambda s: (_signal_decay_points(s, now), s.captured_at), reverse=True)
        top = ranked_signals[0]
        recommended_practice = top.practice_hint
        if practice and recommended_practice != practice:
            continue
        top_age = _age_days(top.captured_at, now)
        rows.append(crm_models.RadarRow(
            lead_id=lead.id, company_name=lead.company_name, industry=lead.industry,
            annual_revenue=lead.annual_revenue, status=lead.status, lead_score=lead.lead_score,
            grade=_grade_for_score(lead.lead_score), signal_points=lead.signal_points or 0,
            recommended_practice=recommended_practice,
            why_now=f"{_SIGNAL_TYPE_LABEL.get(top.type, top.type)} at {lead.company_name} "
                    f"{_age_label(top_age)} - {top.summary}",
            top_signal=top.type, top_signal_age_days=top_age, signal_count=len(signals),
            owner_employee_id=lead.owner_employee_id,
        ))
    rows.sort(key=lambda r: r.lead_score, reverse=True)
    return rows


def _fallback_next_best_action(
    lead: Lead, top_signal: Signal | None, grade: str,
) -> crm_models.NextBestActionOut:
    """Deterministic recommendation used when no AI key is configured (or
    the AI call itself fails) - Radar's core "what do I do next" feature
    must never 503 over that, same reasoning as get_optional_llm_client()."""
    if top_signal is not None and top_signal.type in (
        SignalType.RFP_TENDER.value, SignalType.FILING_EARNINGS.value,
    ):
        channel, due_in_days = LeadCommunicationChannel.CALL.value, 1
    elif lead.linkedin_url:
        channel, due_in_days = LeadCommunicationChannel.LINKEDIN.value, 2
    else:
        channel, due_in_days = LeadCommunicationChannel.EMAIL.value, 3
    due_in_days = {"A": 1, "B": 2, "C": 5, "D": 10}.get(grade, due_in_days)
    if top_signal is not None:
        type_label = _SIGNAL_TYPE_LABEL.get(top_signal.type, top_signal.type)
        why_now = f"{type_label} - {top_signal.summary}"
        action = f"Reach out to {lead.company_name} referencing their recent {type_label.lower()}."
    else:
        why_now = f"No verified external signal yet - grade {grade} on rule-based score alone."
        action = f"Follow up with {lead.company_name} to re-qualify interest."
    return crm_models.NextBestActionOut(
        lead_id=lead.id, action=action, channel=channel, why_now=why_now, due_in_days=due_in_days,
        recommended_practice=top_signal.practice_hint if top_signal else None,
        suggested_cadence_template_id=None, source="fallback",
    )


@handle_errors("generate next best action")
def generate_next_best_action(
    user: CurrentUser, lead_repo: LeadRepository, signal_repo: SignalRepository,
    cadence_template_repo: CadenceTemplateRepository, llm_client: LLMClient | None, lid,
) -> crm_models.NextBestActionOut:
    """Grounded strictly in this lead's own fields/signals/score - unlike
    generate_web_lead_enrichment(), never asked to recall outside facts.
    Falls back to a deterministic recommendation when no AI key is
    configured, or if the AI call itself fails (a flaky/misconfigured
    provider must never take down Radar's core worklist feature)."""
    lead = _get_lead_or_404(lead_repo, lid)
    _require_read_scope(user, lead, "Lead is outside your data scope.")
    now = _now()
    signals = signal_repo.list_for_lead(lid)
    ranked_signals = sorted(signals, key=lambda s: (_signal_decay_points(s, now), s.captured_at), reverse=True)
    top_signal = ranked_signals[0] if ranked_signals else None
    grade = _grade_for_score(lead.lead_score)
    practice = top_signal.practice_hint if top_signal else None
    templates = [t for t in cadence_template_repo.list() if t.is_active]
    suggested_template_id = next(
        (t.id for t in templates if practice and practice.lower() in (t.name or "").lower()), None)

    fallback = _fallback_next_best_action(lead, top_signal, grade)
    if suggested_template_id is not None:
        fallback.suggested_cadence_template_id = suggested_template_id
    if llm_client is None:
        return fallback

    system_prompt = (
        "You are a B2B sales-enablement assistant. Base your recommendation ONLY on the facts given "
        "below - never invent outside information about the company. Respond with ONLY a JSON object "
        'of the shape {"action": "...", "channel": "EMAIL|CALL|LINKEDIN", "why_now": "...", '
        '"due_in_days": int} and nothing else. `action` is one concise, concrete next step a sales rep '
        "should take today. `why_now` cites the specific signal or score fact that justifies acting "
        "now. `due_in_days` is 1-14.")
    signal_lines = "\n".join(
        f"- {_SIGNAL_TYPE_LABEL.get(s.type, s.type)} ({s.source}, {_age_label(_age_days(s.captured_at, now))}): "
        f"{s.summary}" for s in ranked_signals[:5]
    ) or "- No verified external signals yet."
    user_prompt = (
        f"Company: {lead.company_name}\nLead status: {lead.status}\nComposite score: {lead.lead_score} "
        f"(grade {grade})\nSignals:\n{signal_lines}")

    try:
        text = llm_client.complete(system_prompt, user_prompt)
        parsed = _parse_json_response(text, {"action", "channel", "why_now", "due_in_days"})
        channel = str(parsed["channel"]).upper()
        if channel not in {c.value for c in LeadCommunicationChannel}:
            channel = fallback.channel
        try:
            due_in_days = max(1, min(14, int(parsed["due_in_days"])))
        except (TypeError, ValueError):
            due_in_days = fallback.due_in_days
        return crm_models.NextBestActionOut(
            lead_id=lead.id, action=str(parsed["action"]), channel=channel,
            why_now=str(parsed["why_now"]), due_in_days=due_in_days,
            recommended_practice=practice, suggested_cadence_template_id=suggested_template_id,
            source="ai",
        )
    except DomainError:
        return fallback
