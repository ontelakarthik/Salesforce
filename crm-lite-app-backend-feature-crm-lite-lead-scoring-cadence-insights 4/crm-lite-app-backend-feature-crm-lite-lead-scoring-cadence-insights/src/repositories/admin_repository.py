"""Admin module repositories (§1/§13.5 of the API spec) — real, Postgres-
backed data access for every table this module owns. This is the central
"database logic" layer: developers building admin_service.py /
admin_routes.py (and the Auth module's SSO callback, auth_service.py) call
these classes directly and never open a Session themselves.

Tables covered: role (Profile lookup), role_capability (Profile's granted
capabilities), employee, employee_role (association), team.
"""
from functools import lru_cache
from uuid import UUID

from sqlalchemy import select

from src.models.admin_models import Employee, EmployeeRole, Profile, ProfileCapability, Team, Territory
from src.repositories._base import CrudRepository, SoftDeleteCrudRepository


class ProfileRepository(CrudRepository[Profile]):
    model = Profile


class TerritoryRepository(CrudRepository[Territory]):
    model = Territory


class RoleCapabilityRepository(SoftDeleteCrudRepository[ProfileCapability]):
    model = ProfileCapability

    def list_for_role(self, role_id: int) -> list[ProfileCapability]:
        return self.list(role_id=role_id)

    def hard_delete(self, id_) -> None:
        """A full-replace Save on one profile's capability set — same
        reasoning as FieldPermissionRepository.hard_delete(): soft-deleting
        old rows would leave them occupying the (role_id, capability_key)
        unique index, blocking a future save that re-grants the same key."""
        CrudRepository.delete(self, id_)


class EmployeeRepository(SoftDeleteCrudRepository[Employee]):
    model = Employee

    def find_by_entra_object_id(self, entra_object_id: str) -> Employee | None:
        with self._session_factory() as db:
            stmt = select(Employee).where(
                Employee.entra_object_id == entra_object_id, Employee.deleted_at.is_(None))
            return db.execute(stmt).scalar_one_or_none()

    def find_by_email(self, email: str) -> Employee | None:
        with self._session_factory() as db:
            stmt = select(Employee).where(
                Employee.deleted_at.is_(None), Employee.email.ilike(email))
            return db.execute(stmt).scalar_one_or_none()


class EmployeeRoleRepository:
    """Composite-key (employee_id, role_id) association — doesn't fit the
    single-id CrudRepository shape, so this class exposes its own small,
    purpose-built methods instead."""

    def __init__(self) -> None:
        from src.services.db_client import get_session_factory
        self._session_factory = get_session_factory()

    def list_for_employee(self, employee_id: UUID) -> list[EmployeeRole]:
        with self._session_factory() as db:
            stmt = select(EmployeeRole).where(EmployeeRole.employee_id == employee_id)
            return list(db.execute(stmt).scalars().all())

    def list_for_role(self, role_id: int) -> list[EmployeeRole]:
        with self._session_factory() as db:
            stmt = select(EmployeeRole).where(EmployeeRole.role_id == role_id)
            return list(db.execute(stmt).scalars().all())

    def list_for_roles(self, role_ids: set[int]) -> list[EmployeeRole]:
        """Batched counterpart to list_for_role() — used by
        CurrentUser.subordinate_employee_ids() to resolve every descendant
        role in a hierarchy walk to their holders in one query instead of
        one query per descendant role."""
        if not role_ids:
            return []
        with self._session_factory() as db:
            stmt = select(EmployeeRole).where(EmployeeRole.role_id.in_(role_ids))
            return list(db.execute(stmt).scalars().all())

    def grant(self, employee_id: UUID, role_id: int, granted_by: str | None = None) -> EmployeeRole:
        with self._session_factory() as db:
            row = EmployeeRole(employee_id=employee_id, role_id=role_id, granted_by=granted_by)
            db.merge(row)
            db.commit()
            return row

    def revoke(self, employee_id: UUID, role_id: int) -> None:
        with self._session_factory() as db:
            row = db.get(EmployeeRole, (employee_id, role_id))
            if row is not None:
                db.delete(row)
                db.commit()


class TeamRepository(SoftDeleteCrudRepository[Team]):
    model = Team


@lru_cache(maxsize=1)
def get_profile_repository() -> ProfileRepository:
    return ProfileRepository()


@lru_cache(maxsize=1)
def get_territory_repository() -> TerritoryRepository:
    return TerritoryRepository()


@lru_cache(maxsize=1)
def get_role_capability_repository() -> RoleCapabilityRepository:
    return RoleCapabilityRepository()


@lru_cache(maxsize=1)
def get_employee_repository() -> EmployeeRepository:
    return EmployeeRepository()


@lru_cache(maxsize=1)
def get_employee_role_repository() -> EmployeeRoleRepository:
    return EmployeeRoleRepository()


@lru_cache(maxsize=1)
def get_team_repository() -> TeamRepository:
    return TeamRepository()
