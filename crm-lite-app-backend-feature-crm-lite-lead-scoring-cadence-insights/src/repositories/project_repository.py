"""Project module repositories (§1/§7 of the API spec) — real, Postgres-
backed data access for every table this module owns. This is the central
"database logic" layer: developers building project_service.py /
project_routes.py call these classes directly and never open a Session
themselves.

Tables covered: project_status (lookup), project.
"""
from functools import lru_cache

from sqlalchemy import select

from src.models.project_models import Project, ProjectStatus
from src.repositories._base import CrudRepository, SoftDeleteCrudRepository, next_business_id


class ProjectStatusRepository(CrudRepository[ProjectStatus]):
    model = ProjectStatus


class ProjectRepository(SoftDeleteCrudRepository[Project]):
    model = Project

    def next_id(self) -> str:
        with self._session_factory() as db:
            return next_business_id(db, Project, "id", "PRJ-")

    def list_for_account(self, account_id: str) -> list[Project]:
        return self.list(account_id=account_id)

    def count_active_for_account(self, account_id: str) -> int:
        """Projects not yet CLOSED for this account. Handy for the CRM
        module's delete-blocked-by-dependents rule."""
        with self._session_factory() as db:
            stmt = (
                select(Project.id)
                .join(ProjectStatus, Project.project_status_id == ProjectStatus.id)
                .where(
                    Project.account_id == account_id,
                    Project.deleted_at.is_(None),
                    ProjectStatus.is_terminal.is_(False),
                )
            )
            return len(db.execute(stmt).all())


@lru_cache(maxsize=1)
def get_project_status_repository() -> ProjectStatusRepository:
    return ProjectStatusRepository()


@lru_cache(maxsize=1)
def get_project_repository() -> ProjectRepository:
    return ProjectRepository()
