"""Shared account-ownership data-scoping helper.

SALES sees only the accounts they own (Account.owner_employee_id); a profile
holding the `records.see_all` capability sees every account (seeded to
ACCOUNT_EXEC/LEADERSHIP/ADMIN — see the migration that introduced
role_capability). Every module whose rows hang off an account — directly
(Account, Opportunity), or indirectly via an agreement/project that itself
belongs to an account (Agreement, Project, and every SOW sub-resource keyed
off agreement_id) — calls this instead of re-deriving its own copy of the
rule, so the rule can't drift module-to-module.

crm_service.py's own _hierarchy_scope()/_owned_by() cover the case where the
row itself carries owner_employee_id directly (Account, Opportunity, Lead);
this module covers everything one hop further out, where only an account_id
FK is available (Agreement, Project, SOW sub-resources), plus the Lead case
(Lead-level communications/insights).

Both owned_account_ids()/require_account_scope() and require_lead_scope() are
also Organization-Wide-Default-aware (see crm_models.OrgWideDefault /
crm_service._in_read_scope()/_in_write_scope()): the ACCOUNT/LEAD OWD widens
the read side whenever it's PUBLIC_READ_ONLY or PUBLIC_READ_WRITE, and the
write side only for PUBLIC_READ_WRITE — pass `for_write=True` at any call site
that mutates the row (or a resource hanging off it) rather than just reading
it; the default (`for_write=False`) preserves today's read-only-widening
behavior for every existing caller.
"""
from src.models.enums import OrgWideDefaultAccessLevel
from src.repositories.crm_repository import AccountRepository, LeadRepository, get_org_wide_default_repository
from src.utils.exceptions import DomainError
from src.utils.security import CurrentUser


def sees_all(user: CurrentUser) -> bool:
    """True for profiles with no account-ownership restriction."""
    return user.has_capability("records.see_all")


def _owd_widens(object_name: str, *, for_write: bool) -> bool:
    level = get_org_wide_default_repository().get_by_object(object_name)
    access_level = level.access_level if level is not None else OrgWideDefaultAccessLevel.PRIVATE.value
    if for_write:
        return access_level == OrgWideDefaultAccessLevel.PUBLIC_READ_WRITE.value
    return access_level in (
        OrgWideDefaultAccessLevel.PUBLIC_READ_ONLY.value,
        OrgWideDefaultAccessLevel.PUBLIC_READ_WRITE.value,
    )


def owned_account_ids(user: CurrentUser, account_repo: AccountRepository, *,
                       for_write: bool = False) -> set[str] | None:
    """None means "no restriction" — sees_all(), or (per `for_write`) the
    ACCOUNT Organization-Wide Default already opens this up for everyone;
    otherwise the set of account ids a SALES user is scoped to — their own
    accounts plus any owned by an employee holding a profile beneath theirs
    in the Role Hierarchy (see CurrentUser.subordinate_employee_ids()). Any
    row whose account_id isn't in this set — an account, or anything hanging
    off one (agreement, project, SOW sub-resource, ...) — is outside that
    user's data scope."""
    if sees_all(user) or _owd_widens("ACCOUNT", for_write=for_write):
        return None
    owner = user.employee_uuid()
    owner_ids = ({owner} if owner is not None else set()) | user.subordinate_employee_ids()
    if not owner_ids:
        return set()
    return {c.id for c in account_repo.list_for_owners(owner_ids)}


def require_account_scope(user: CurrentUser, account_repo: AccountRepository, account_id: str,
                           message: str = "Outside your data scope.", *, for_write: bool = False) -> None:
    """Raise FORBIDDEN if `account_id` isn't in the caller's data scope —
    the common single-row check for a get/list-sub-resource on any entity
    that hangs off an account, directly or through an agreement/project.
    Pass for_write=True for any call that mutates the row (or a resource
    hanging off it) rather than just reading it."""
    owned = owned_account_ids(user, account_repo, for_write=for_write)
    if owned is not None and account_id not in owned:
        raise DomainError("FORBIDDEN", message, 403)


def require_lead_scope(user: CurrentUser, lead_repo: LeadRepository, lead_id,
                        message: str = "Lead is outside your data scope.", *,
                        for_write: bool = False) -> None:
    """Mirrors require_account_scope, but for rows that hang off a Lead
    (which carries owner_employee_id directly, like Account) rather than an
    account_id FK — e.g. Lead-level communications/insights. Pass
    for_write=True for any call that mutates the row (or a resource hanging
    off it) rather than just reading it."""
    if sees_all(user) or _owd_widens("LEAD", for_write=for_write):
        return
    lead = lead_repo.get(lead_id)
    if lead is None:
        return  # let the caller's own not-found check surface the 404
    owner = user.employee_uuid()
    owner_ids = ({owner} if owner is not None else set()) | user.subordinate_employee_ids()
    if lead.owner_employee_id not in owner_ids:
        raise DomainError("FORBIDDEN", message, 403)
