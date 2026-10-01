"""RBAC — capability gating via requires().

Object-level access ("can this profile call this capability at all") used
to be a fixed Python dict keyed by a 4-role enum. It's now admin-configurable:
which profiles hold which capability lives in the `role_capability` table
(src/models/admin_models.py::ProfileCapability), edited via the
/admin/profiles/{id}/capabilities matrix (src/services/admin_service.py).

CAPABILITY_REGISTRY below is NOT the grant table — it's the fixed universe of
valid capability keys this codebase understands (mirrors FLS's own
_FLS_FIELDS: static "what exists" vs. DB "what's granted"), used to validate
admin input (reject an unknown key) and to build the admin capability-matrix
UI. requires(capability) checks CurrentUser.capabilities — computed once at
login (auth_service._capabilities_for(), DB-driven) and baked into the JWT —
so this stays a zero-per-request-DB-cost, in-memory membership check exactly
like before; only where the allowed-set comes from changed.

The 4 originally-seeded profiles (SALES/ACCOUNT_EXEC/LEADERSHIP/ADMIN) are
seeded, via the migration that introduced role_capability, with grants that
exactly reproduce this dict's old fixed mapping — see that migration for the
authoritative seed data, not this file.

records.see_all/audit.see_all are new: they formalize what used to be three
independently-copy-pasted role tuples (_ALL_SCOPE_ROLES in crm_service.py/
platform_service.py/scope.py — confirmed to be the same account/lead-
ownership-scoping rule duplicated three times, not three distinct concepts)
and one narrower one (_SEES_ALL_AUDIT_ROLES in activity_service.py) into the
same admin-editable mechanism as every other capability, rather than a
second, hardcoded scoping system living alongside CAPABILITY_REGISTRY.

campaigns.write/leads.write/leads.convert mirror accounts.write/
accounts.promote's role set exactly — Lead conversion produces an Account,
so whoever's allowed to create one directly is allowed to produce one via
conversion too.

lead_scoring_rules.write/cadence_templates.write/products.write/
field_permissions.write are ADMIN-only in the seed data: all four are
shared, global config with cross-team blast radius (a scoring rule reshapes
every rep's lead prioritization; an uncurated pile of rep-authored cadence
templates undermines the "reusable playbook" value; the product catalog is
what every rep's AI-drafted email/call-prep gets matched against; one saved
FLS matrix changes what every rep of a given profile can see/edit) — same
tier as `admin`. cadences.enroll mirrors leads.write exactly — enrolling/
advancing a lead through a cadence is a day-to-day lead-working action, not
config.

manager_dashboard.read (seeded to AE/L/A, mirrors audit.read) is deliberately
NOT platform.read — unlike every other list endpoint, it shows every rep's
numbers with no per-row ownership scoping, so SALES (a BDE) doesn't get it;
only profiles that map to Manager/Leadership/Admin do.

leads.flag_hot (seeded to L/A) is a deliberately narrow carve-out: LEADERSHIP
has no general write access to Lead (see leads.write above) but needs a way
to flag a lead as HOT/actively-being-worked from the manager dashboard
without opening full edit rights — it only ever sets Lead.rating, nothing
else. SALES/ACCOUNT_EXEC already have full leads.write and don't need this
separate route.

Reading your OWN effective field permissions (GET .../effective) is under
platform.read instead of field_permissions.write — every real profile needs
that just to render its own screens.

leads.create/leads.edit/leads.delete, accounts.create/accounts.edit/
accounts.delete, opportunities.create/opportunities.edit/opportunities.delete
(added alongside the older X.write keys, not replacing them — see the
migration that introduced them) gate ONLY the object's own POST/PATCH/DELETE
route. leads.write/accounts.write/opportunities.write still gate everything
else they always did (AI-drafting actions and lead communications; contact
CRUD and account/agreement communications; opportunity-document add/update)
— narrowing or retiring those keys would mean re-auditing every one of those
other routes individually, which is out of scope here. accounts.delete is a
genuinely new capability (DELETE /accounts/{id} used to be gated by the bare
`admin` key, an inconsistency with the rest of the object's now-fine-grained
CRUD) — seeded ADMIN-only, identical effective behavior on day one, but now
an admin can deliberately widen it like any other cell in the grid.

leads.read/accounts.read/opportunities.read take over gating GET (list +
detail) for just those three objects, in place of the shared platform.read —
every other platform.read-gated route (45 of the 51 total call sites,
spanning timesheets/agreements/projects/contracts/delivery/sub-resources of
these same three objects) is untouched, an explicit scope decision, not an
oversight.

records.see_all remains a per-EMPLOYEE, all-object override (a profile either
sees everything or doesn't) — Organization-Wide Defaults (see
crm_models.OrgWideDefault / crm_service._in_read_scope()/_in_write_scope())
now supply the per-OBJECT piece that used to be missing: an admin can widen
LEAD to org-wide-readable without touching ACCOUNT/OPPORTUNITY, or without
granting records.see_all to anyone. The two layer together — a Lead visible
under LEAD's OWD is visible regardless of records.see_all, and records.see_all
still sees every object regardless of any OWD setting.
org_wide_defaults.write (ADMIN-only in the seed data) gates
GET/PUT /admin/org-wide-defaults, the same tier as field_permissions.write:
shared, global config whose blast radius is every rep's row visibility for
that object.
"""
from fastapi import Depends, HTTPException, status

from src.utils.security import CurrentUser, get_current_user

CAPABILITY_REGISTRY: dict[str, str] = {
    "platform.read": "Read access to the app's own list/detail screens.",
    "campaigns.write": "Create/update/delete campaigns.",
    "leads.write": "Lead sub-resource/action routes: AI drafting, communications.",
    "leads.create": "Create a lead.",
    "leads.edit": "Edit a lead.",
    "leads.delete": "Delete a lead.",
    "leads.read": "Read leads (list and detail).",
    "leads.convert": "Convert a qualified lead into an Account/Contact/Opportunity.",
    "leads.flag_hot": "Flag any lead HOT from the manager dashboard (sets Lead.rating only).",
    "lead_scoring_rules.write": "Edit the global lead-scoring rule set.",
    "cadence_templates.write": "Edit the global sales-cadence template library.",
    "field_permissions.write": "Edit the Field-Level Security matrix.",
    "org_wide_defaults.write": "Edit the per-object Organization-Wide Default sharing baseline.",
    "record_shares.write": "Grant/revoke a user-based sharing grant on a Lead/Account/Contact/"
                           "Opportunity/Campaign record you can already edit.",
    "products.write": "Edit the product catalog.",
    "cadences.enroll": "Enroll/advance a lead through a sales cadence.",
    "manager_dashboard.read": "Read every rep's numbers on the manager dashboard, unscoped.",
    "accounts.write": "Account sub-resource/action routes: contacts, communications.",
    "accounts.create": "Create an account.",
    "accounts.edit": "Edit an account.",
    "accounts.delete": "Delete an account.",
    "accounts.read": "Read accounts (list and detail).",
    "accounts.promote": "Promote an account from Prospect to Client.",
    "accounts.assign": "Reassign an account's owner.",
    "opportunities.write": "Opportunity sub-resource/action routes: documents.",
    "opportunities.create": "Create an opportunity.",
    "opportunities.edit": "Edit an opportunity.",
    "opportunities.delete": "Delete an opportunity.",
    "opportunities.read": "Read opportunities (list and detail).",
    "projects.write": "Create/update/delete projects.",
    "agreements.write": "Create/update/delete agreements.",
    "agreements.sign": "Sign an agreement.",
    "sow.write": "Create/update/delete SOW sub-resources.",
    "timesheets.read": "Read timesheets.",
    "timesheets.submit": "Submit/edit your own timesheet.",
    "timesheets.approve": "Approve any timesheet (also grants seeing every timesheet, not just your own).",
    "audit.read": "Read the audit log.",
    "admin": "Admin-only CRUD: employees, teams, lookups, profiles.",
    "records.see_all": "See every Account/Lead/Opportunity row, not just ones you own.",
    "audit.see_all": "See every audit-log row, not just ones you performed.",
}


def requires(capability: str):
    if capability not in CAPABILITY_REGISTRY:  # KeyError = typo, fail closed
        raise KeyError(capability)

    def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has_capability(capability):
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                {"code": "FORBIDDEN", "message": f"Profile not permitted for '{capability}'."})
        return user

    return _dep
