"""Centralized record-level access decisions for Lead, Account, Contact,
Opportunity, and Campaign — Salesforce-style Organization-Wide Defaults +
record ownership + Role Hierarchy + user-based Sharing Rules, layered
underneath (never replacing) the existing capability/records.see_all system.

Role Hierarchy (CurrentUser.subordinate_employee_ids(), walking the
admin-configurable Profile.parent_role_id tree) is included here as of the
Sales Territory/Region feature: a manager gets the same READ/EDIT (never
DELETE) access to a record their org-chart subordinate owns as the owner
themselves would. src/utils/scope.py's owned_account_ids()/
require_account_scope()/require_lead_scope() (Agreement/Project/SOW/
Communications) and crm_service.py's own _hierarchy_scope() (still used only
by list_my_cadence_tasks()'s literal-"my tasks" carve-out) already did this
for every other module — this file used to be the one deliberate exception;
it no longer is. Two peers holding the same profile are still NOT each
other's subordinates (see subordinate_employee_ids()'s own docstring), so
this never grants access between same-territory/same-role coworkers on its
own — see the Territory paragraph below for why Territory itself doesn't
change that.

Sales Territory/Region (admin_models.Territory, Employee/Account/Lead.
territory_id) is deliberately NOT part of this decision. It is data plus a
defaulting convenience (a new Account/Lead defaults to its owner's
territory — see crm_service.create_account()/create_lead()), never a
sharing/grant mechanism: two employees in the same territory do not
automatically see each other's private records merely for sharing that
territory. Widening visibility by territory (e.g. a future "territory
manager" capability) is a deliberately separate, not-yet-requested
extension — nothing here forecloses adding it later without another schema
change, but it does not exist today.

Precedence (first match wins):
    1. records.see_all capability            -> full access
    2. record ownership (direct, or for      -> full access (READ/EDIT;
       CONTACT, derived from the parent          DELETE still separately
       Account's owner)                          gated by the object's own
                                                   delete capability)
    3. Role Hierarchy (a manager of the       -> READ/EDIT only, never
       owner, per subordinate_employee_ids())    DELETE
    4. Organization-Wide Default              -> PUBLIC_READ_WRITE grants
                                                   READ+EDIT; PUBLIC_READ_ONLY
                                                   grants READ only
    5. a RecordShare row                      -> grants exactly what it says
                                                   (READ or EDIT), never DELETE

Sharing only ever ADDS access on top of OWD/ownership/hierarchy — it is
checked last and can't be reached at all once an earlier layer already
granted the requested level.
"""
from uuid import UUID

from src.models.enums import OrgWideDefaultAccessLevel, RecordAccessLevel
from src.repositories.crm_repository import (
    AccountRepository,
    OrgWideDefaultRepository,
    RecordShareRepository,
    get_account_repository,
    get_org_wide_default_repository,
)
from src.utils.exceptions import DomainError
from src.utils.security import CurrentUser

#: Objects this service governs — mirrors crm_service._OWD_OBJECTS (kept in
#: sync there; duplicated here rather than imported to avoid a crm_service
#: <-> record_access_service circular import).
RECORD_ACCESS_OBJECTS = {"LEAD", "ACCOUNT", "CONTACT", "OPPORTUNITY", "CAMPAIGN"}


def _employee_uuid(user: CurrentUser) -> UUID | None:
    try:
        return UUID(str(user.employee_id))
    except ValueError:
        return None


def _matches(user: CurrentUser, employee_id) -> bool:
    if employee_id is None:
        return False
    caller = _employee_uuid(user)
    return caller is not None and caller == employee_id


def effective_owner_employee_id(object_name: str, record, account_repo: AccountRepository | None = None):
    """CONTACT has no owner_employee_id of its own — it's derived from its
    parent Account's owner (see crm_models.Contact / this feature's design:
    "do not add contact.owner_employee_id"). Every other object
    (LEAD/ACCOUNT/OPPORTUNITY/CAMPAIGN) carries owner_employee_id directly."""
    if object_name == "CONTACT":
        repo = account_repo or get_account_repository()
        account = repo.get(record.account_id)
        return account.owner_employee_id if account is not None else None
    return record.owner_employee_id


def _owd_level(object_name: str, owd_repo: OrgWideDefaultRepository) -> str:
    row = owd_repo.get_by_object(object_name)
    # Defensive fallback if a row is ever missing (shouldn't happen once the
    # introducing migration has run) — PRIVATE is the safe default.
    return row.access_level if row is not None else OrgWideDefaultAccessLevel.PRIVATE.value


def can_user_access_record(
    user: CurrentUser, object_name: str, record, required: RecordAccessLevel, *,
    share_repo: RecordShareRepository,
    owd_repo: OrgWideDefaultRepository | None = None,
    account_repo: AccountRepository | None = None,
) -> bool:
    """The one function every route/service call for Lead/Account/Contact/
    Opportunity/Campaign delegates to instead of re-deriving its own scope
    rule. `record` must expose `.id`, and (for everything except CONTACT)
    `.owner_employee_id`; CONTACT rows must expose `.account_id` instead."""
    if user.has_capability("records.see_all"):
        return True

    owner_id = effective_owner_employee_id(object_name, record, account_repo)
    if _matches(user, owner_id):
        return True

    if required == RecordAccessLevel.DELETE:
        # Sharing and Role Hierarchy never grant DELETE — owner/
        # records.see_all (both already checked above) are the only paths,
        # on top of the object's own existing delete capability enforced at
        # the route layer.
        return False

    # Role Hierarchy: a manager (per the admin-configurable Profile tree)
    # gets the same READ/EDIT the owner has. Peers holding the same profile
    # are never subordinates of each other (see subordinate_employee_ids()'s
    # own docstring) — this is what keeps two same-territory coworkers from
    # seeing each other's PRIVATE records just by sharing a territory (see
    # this module's docstring).
    if owner_id is not None and owner_id in user.subordinate_employee_ids():
        return True

    level = _owd_level(object_name, owd_repo or get_org_wide_default_repository())
    if level == OrgWideDefaultAccessLevel.PUBLIC_READ_WRITE.value:
        return True
    if level == OrgWideDefaultAccessLevel.PUBLIC_READ_ONLY.value and required == RecordAccessLevel.READ:
        return True

    caller = _employee_uuid(user)
    if caller is None:
        return False
    return share_repo.has_access(object_name, str(record.id), caller, required)


def require_record_access(
    user: CurrentUser, object_name: str, record, required: RecordAccessLevel, *,
    share_repo: RecordShareRepository,
    owd_repo: OrgWideDefaultRepository | None = None,
    account_repo: AccountRepository | None = None,
    message: str | None = None,
) -> None:
    if not can_user_access_record(
        user, object_name, record, required,
        share_repo=share_repo, owd_repo=owd_repo, account_repo=account_repo,
    ):
        raise DomainError(
            "FORBIDDEN", message or f"{object_name.title()} is outside your data scope.", 403)


def compute_permissions(
    user: CurrentUser, object_name: str, record, *,
    share_repo: RecordShareRepository,
    owd_repo: OrgWideDefaultRepository | None = None,
    account_repo: AccountRepository | None = None,
) -> tuple[bool, bool]:
    """(can_edit, can_delete) for a single record — the pair every *Out
    schema for these 5 objects now carries, computed server-side so the
    frontend never re-derives access logic itself."""
    can_edit = can_user_access_record(
        user, object_name, record, RecordAccessLevel.EDIT,
        share_repo=share_repo, owd_repo=owd_repo, account_repo=account_repo)
    can_delete = can_user_access_record(
        user, object_name, record, RecordAccessLevel.DELETE,
        share_repo=share_repo, owd_repo=owd_repo, account_repo=account_repo)
    return can_edit, can_delete
