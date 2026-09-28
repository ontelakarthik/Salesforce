"""Models for the Admin module (§1/§13.5 of the API spec) — employee
provisioning, role assignment, teams/DLs, lookup value management.

Full ORM schema implemented (the central "database logic" every developer
builds their service/route layer on top of) — business logic itself
(Pattern-A provisioning, unique/immutable lookup codes, LOOKUP_IN_USE checks)
is NOT here; see services/admin_service.py for what still needs to be
written, and repositories/admin_repository.py for the ready-to-use
data-access classes.

Tables owned: employee, role (lookup), employee_role (association), team —
the shared identity/foundation tables every other module's employee_id/
team_id FKs point at, provisioned here per Pattern A (Admin pre-creates the
employee row; the Auth module's SSO callback links the Entra identity to it
on first login — see auth_models.py / auth_service.py). Lookup-table
*management* (GET/POST/PATCH /admin/lookups/{table}) is also Admin's, but the
individual lookup tables themselves (account_type, agreement_type,
project_status, opportunity_stage, contact_type, agreement_status) live
alongside their owning domain's models file — only `role` lives here since
it's Admin's own foundation lookup.
"""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import AuditMixin, Base, SoftDeleteMixin
from src.models.common import AuditOut, ORMModel


class Profile(Base):
    """A named, admin-manageable bundle of capabilities (Salesforce-style
    Profile) — replaces the old fixed 4-role enum as the unit of RBAC
    assignment. Table name stays `role` (and the FK column on every table
    that references it stays `role_id`) deliberately: this is a Python/API-
    level rename only, not a DB rename, so field_permission.role_id and
    every other existing FK keeps working untouched. `is_system` protects
    the 4 originally-seeded profiles (SALES/ACCOUNT_EXEC/LEADERSHIP/ADMIN)
    from deletion/code changes; an admin-created profile has is_system=False
    and starts with zero granted capabilities (see role_capability) —
    deliberately default-deny, unlike Field-Level Security's default-allow,
    since this is the PRIMARY object-access gate, not a narrowing layer on
    top of already-granted access.

    `parent_role_id` is the admin-configurable Role Hierarchy: holding a
    profile grants visibility into every business record owned by anyone
    holding a profile strictly beneath it in this tree (see
    CurrentUser.subordinate_employee_ids()), additive to (not a replacement
    for) the records.see_all capability. NULL means top-level/unplaced —
    every profile starts this way, so a flat tree is the zero-behavior-
    change default."""
    __tablename__ = "role"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    parent_role_id: Mapped[int | None] = mapped_column(ForeignKey("role.id"), nullable=True)


class ProfileCapability(Base, AuditMixin, SoftDeleteMixin):
    """Admin-managed object-level access grant — presence of a row means
    `role_id` (a Profile) is granted `capability_key` (one of
    utils.permissions.CAPABILITY_REGISTRY's keys). No boolean needed (unlike
    field_permission's visible/editable pair) since a capability is a single
    yes/no grant. Table name `role_capability` (not `profile_capability`)
    for the same reason Profile keeps the `role` table name — this whole
    feature is a Python/API vocabulary change, not a DB one."""
    __tablename__ = "role_capability"
    __table_args__ = (
        Index(
            "ix_role_capability_role_key", "role_id", "capability_key",
            unique=True, postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_id: Mapped[int] = mapped_column(ForeignKey("role.id"))
    capability_key: Mapped[str] = mapped_column(String(60))


class Territory(Base):
    """Sales Territory master object — a business access-control/assignment
    concept, deliberately separate from (and never auto-equated with) an
    Account/Lead's Billing Country/State (see src/utils/geo.py, which that
    pair already derives a Region from). Plain lookup table (no
    AuditMixin/SoftDeleteMixin), same base shape as AccountType/ContactType
    in crm_models.py, plus `is_active` so an admin can retire a territory
    without deleting it (and without it disappearing from the history of any
    record already assigned to it), and `description`/`country`/`region` —
    the fields this object needs that no other lookup table does. Lives
    here, not in crm_models.py, because Employee — not just Account/Lead —
    carries a territory_id FK to it; same "shared foundation table other
    modules' FKs point at" treatment as Profile/Team above.

    `code` is nullable (unlike every other lookup table's `code`) since a
    Territory is meaningfully identified by Name/Country/Region alone and
    Code is an optional short-hand here, not a business key — the existing
    unique constraint is left in place (Postgres allows any number of NULLs
    under a unique constraint) so a Code, when given, still can't collide.
    `country` is required and must be one of geo.py's supported countries;
    `region`, unlike country, is optional — a country-wide/top-level
    territory (e.g. "USA" itself, parent of "USA - West") legitimately has
    no single region — but when given, `region` must be one of that
    country's existing derived Region values (see utils.geo.valid_regions())
    — reusing that vocabulary as-is rather than inventing a second Region
    concept; enforced in services/admin_service.py's
    _validate_territory_fields() since the generic LookupCreate/Update
    schema can't express per-table required-ness.

    Exactly USA/CANADA (top-level, one per country) plus one child territory
    per that country's real geo.py region (e.g. "USA - West", "Canada -
    Atlantic") are seeded active by migration — managed like any other
    reference table via the existing generic /admin/lookups/territory
    endpoints (see admin_service._LOOKUP_TABLES) — no bespoke CRUD needed.
    Assigning one to an Employee/Account/Lead is a plain data/defaulting
    concern (see Employee.territory_id below and
    crm_models.Account.territory_id/Lead.territory_id) — it never, on its
    own, widens who can see a record; see
    services/record_access_service.py's module docstring for why."""
    __tablename__ = "territory"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    # Named display_name (not `name`), matching every other lookup table
    # (AccountType/ContactType/OpportunityStage/Profile) so it drops straight
    # into the existing generic LookupOut/LookupCreate/LookupUpdate shape —
    # see admin_service._LOOKUP_TABLES/_lookup_fields().
    display_name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    country: Mapped[str | None] = mapped_column(String(64), nullable=True)
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Self-reference for a territory hierarchy (Salesforce Territory2-style
    # parent/child tree — e.g. "USA" as the parent of "USA - West") — same
    # nullable-self-FK shape as Profile.parent_role_id, and the same
    # cycle-detection pattern (see admin_service._validate_territory_parent(),
    # mirroring _validate_new_parent()) applied to this tree instead. NULL
    # means top-level, same zero-behavior-change default as Profile's.
    parent_territory_id: Mapped[int | None] = mapped_column(ForeignKey("territory.id"), nullable=True)


class Employee(Base, AuditMixin, SoftDeleteMixin):
    __tablename__ = "employee"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entra_object_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    full_name: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Sales Territory/Region this employee is assigned to (see Territory
    # above) — part of this employee's authorization/assignment data, used to
    # default the territory of an Account/Lead they create (see
    # crm_service.create_account()/create_lead()). Nullable: an employee with
    # no territory set simply produces unterritoried records, same treatment
    # as owner_employee_id being nullable elsewhere.
    territory_id: Mapped[int | None] = mapped_column(ForeignKey("territory.id"), nullable=True)
    # bcrypt hash, never the plaintext (see utils/passwords.py). Nullable:
    # an employee provisioned but not yet given login access has no password
    # set and simply can't log in yet (auth_service.login() rejects it as
    # NO_PASSWORD_SET, not a 500).
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # True for a system-generated temp password (see admin_service.
    # create_employee()) until the employee sets their own via
    # POST /auth/change-password.
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)

    roles: Mapped[list["EmployeeRole"]] = relationship(back_populates="employee")


class EmployeeRole(Base):
    """Association row: which roles an employee holds. Granting/revoking a
    role is an insert/delete of this row, not a soft-delete."""
    __tablename__ = "employee_role"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employee.id"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("role.id"), primary_key=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    granted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

    employee: Mapped["Employee"] = relationship(back_populates="roles")
    role: Mapped["Profile"] = relationship()


class Team(Base, AuditMixin, SoftDeleteMixin):
    __tablename__ = "team"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    display_name: Mapped[str] = mapped_column(String(255))
    purpose: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)  # DL email / physical address
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


# --- request/response (Pydantic) schemas ------------------------------------


class EmployeeCreate(BaseModel):
    email: str = Field(max_length=255)
    full_name: str = Field(min_length=1, max_length=255)
    # Territory.id directly — NOT the territory's code, which is optional
    # and can be null (see admin_models.Territory.code's docstring); id is
    # the only value that always identifies a territory. Resolved/validated
    # server-side in admin_service.create_employee().
    territory_id: int | None = None


class EmployeeUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None
    territory_id: int | None = None


class EmployeeOut(AuditOut):
    id: uuid.UUID
    entra_object_id: str | None = None
    email: str
    full_name: str
    is_active: bool
    must_change_password: bool
    roles: list[str] = []
    territory_id: int | None = None
    # Resolved display name of territory_id above, for the UI — never the
    # code (see EmployeeCreate.territory_id's docstring). None when
    # territory_id is None, or (defensively) if it points at a row that's
    # since been deleted.
    territory_name: str | None = None


class EmployeeCreateOut(EmployeeOut):
    """POST /admin/employees's response — adds whether the welcome email
    (email + temp password) actually went out, so an admin knows to
    manually share credentials if SMTP isn't configured or delivery failed.
    A failed welcome email does NOT undo the employee's creation."""
    password_email_sent: bool


class EmployeeProfilesUpdate(BaseModel):
    profile_codes: list[str] = Field(default_factory=list)


class ProfileCreate(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    display_name: str = Field(min_length=1, max_length=120)


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    parent_role_id: int | None = None


class ProfileOut(ORMModel):
    id: int
    code: str
    display_name: str
    is_system: bool
    parent_role_id: int | None = None


class CapabilityEntry(BaseModel):
    key: str
    description: str


class ProfileCapabilitiesUpdate(BaseModel):
    capability_keys: list[str] = Field(default_factory=list)


class EmployeeDirectoryEntry(BaseModel):
    """A deliberately minimal projection of Employee — just enough for the
    UI to resolve an owner/signer/reviewer/approver id to a display name
    anywhere in the app (Leads, Opportunities, SOWs, NDAs, Audit Log, ...).
    Unlike GET /admin/employees (admin-only, full record), this is
    available to every authenticated role — no email, roles, or active
    status, so there's nothing sensitive to gate."""
    id: uuid.UUID
    full_name: str


class TeamCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)
    purpose: str | None = Field(default=None, max_length=255)
    address: str | None = Field(default=None, max_length=255)


class TeamUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    purpose: str | None = Field(default=None, max_length=255)
    address: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None


class TeamOut(AuditOut):
    id: int
    display_name: str
    purpose: str | None = None
    address: str | None = None
    is_active: bool


class LookupCreate(BaseModel):
    """Generic lookup-row shape used for every /admin/lookups/{table} target
    (account_type, contact_type, opportunity_stage, agreement_type,
    agreement_status, project_status, call_disposition, territory). Not
    every field applies to every table — the service layer only forwards the
    columns the target table actually has (see admin_service._lookup_fields()).

    `code` is Optional here only because Territory's Code is optional
    (see admin_models.Territory) — every other table still requires it, just
    enforced explicitly in admin_service.add_lookup() now instead of via this
    shared schema, since a schema-level `min_length=1` can't vary by table."""
    code: str | None = Field(default=None, min_length=1, max_length=32)
    display_name: str = Field(min_length=1, max_length=120)
    is_terminal: bool | None = None            # opportunity_stage/agreement_status/project_status only
    default_sla_hours: int | None = None       # agreement_type only
    is_active: bool | None = None              # territory only
    description: str | None = Field(default=None, max_length=500)  # territory only
    country: str | None = Field(default=None, max_length=64)       # territory only, required (see admin_service)
    region: str | None = Field(default=None, max_length=64)        # territory only, optional (a top-level/
                                                                    # country-wide territory has no single region)
    parent_territory_id: int | None = None     # territory only, optional (see admin_models.Territory)


class LookupUpdate(BaseModel):
    # code is immutable after create — not part of Update.
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    is_terminal: bool | None = None
    default_sla_hours: int | None = None
    is_active: bool | None = None              # territory only
    description: str | None = Field(default=None, max_length=500)  # territory only
    country: str | None = Field(default=None, max_length=64)       # territory only
    region: str | None = Field(default=None, max_length=64)        # territory only, optional
    parent_territory_id: int | None = None     # territory only, optional


class LookupOut(ORMModel):
    id: int
    code: str | None = None
    display_name: str
    is_terminal: bool | None = None
    default_sla_hours: int | None = None
    is_active: bool | None = None              # territory only
    description: str | None = None             # territory only
    country: str | None = None                 # territory only
    region: str | None = None                  # territory only
    parent_territory_id: int | None = None     # territory only
