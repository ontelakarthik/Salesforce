"""Generic SQLAlchemy CRUD helpers shared by every module's *_repository.py.

Not a module of its own — owns no tables — just the reusable data-access
building blocks every module's repository classes are built from, so the
central database layer supplies real list/get/create/update/delete against
Postgres for every entity, and a module's own repository file only has to
add the entity-specific query methods (if any) on top.

Usage (from any <module>_repository.py):

    class AccountRepository(SoftDeleteCrudRepository[Account]):
        model = Account

        def next_id(self) -> str:
            with self._session_factory() as db:
                return next_business_id(db, Account, "id", "ACC-")

Then wire a cached singleton + factory the same way every module does:

    @lru_cache(maxsize=1)
    def _singleton() -> AccountRepository:
        return AccountRepository()

    def get_account_repository() -> AccountRepository:
        return _singleton()
"""
from datetime import datetime, timezone
from typing import Generic, TypeVar
from uuid import UUID

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from src.services.db_client import get_session_factory
from src.utils.exceptions import DomainError

ModelT = TypeVar("ModelT")

_SKIP_AUDIT_FIELDS = {"created_at", "updated_at", "created_by", "updated_by"}


def _resolve_employee_uuid(db: Session, value) -> UUID | None:
    """Best-effort parse of an acting-user id (CurrentUser.employee_id, e.g.
    the DEV_AUTH_BYPASS placeholder "dev-admin", or a gateway-forwarded id
    that hasn't been provisioned as an Employee row yet) into a real
    employee.id — audit_log.performed_by_employee_id is a hard FK, so
    anything that isn't both a UUID and an existing employee just leaves the
    column unset rather than failing the write."""
    from src.models.admin_models import Employee  # local import: avoids a
    # circular import (admin_repository.py imports this module)

    if value is None:
        return None
    try:
        employee_uuid = UUID(str(value))
    except ValueError:
        return None
    return employee_uuid if db.get(Employee, employee_uuid) is not None else None


def _entity_id(obj) -> str:
    pk_columns = inspect(obj.__class__).primary_key
    return "/".join(str(getattr(obj, col.name)) for col in pk_columns)


def _write_audit(db: Session, obj, action: str, changed_by: str | None,
                 field: str | None = None, old_value=None, new_value=None) -> None:
    """Append-only trail of every mutation across every module (§1/§11 of the
    API spec) — hooked in here at the shared CRUD base instead of once per
    module's service, so no module can forget to record one. Skips the
    audit_log table itself (nothing to say about writing an audit row)."""
    from src.models.activity_models import AuditLog  # local import: avoids a
    # circular import (activity_repository.py imports this module)

    if isinstance(obj, AuditLog):
        return
    db.add(AuditLog(
        entity_type=obj.__tablename__, entity_id=_entity_id(obj), action=action,
        field_changed=field,
        old_value=None if old_value is None else str(old_value),
        new_value=None if new_value is None else str(new_value),
        performed_by_employee_id=_resolve_employee_uuid(db, changed_by),
    ))


class CrudRepository(Generic[ModelT]):
    """Hard-delete CRUD against a single ORM model. Subclass and set `model`.

    Each call opens and closes its own short-lived session rather than
    reusing a request-scoped one, since repository instances are cached
    singletons (see the factory pattern above) shared across requests.
    """

    model: type[ModelT]

    def __init__(self) -> None:
        self._session_factory = get_session_factory()

    def list(self, **filters) -> list[ModelT]:
        with self._session_factory() as db:
            stmt = select(self.model)
            for column, value in filters.items():
                stmt = stmt.where(getattr(self.model, column) == value)
            return list(db.execute(stmt).scalars().all())

    def get(self, id_) -> ModelT | None:
        with self._session_factory() as db:
            return db.get(self.model, id_)

    def create(self, **fields) -> ModelT:
        with self._session_factory() as db:
            obj = self.model(**fields)
            db.add(obj)
            db.flush()
            _write_audit(db, obj, "CREATE", fields.get("created_by"))
            db.commit()
            db.refresh(obj)
            return obj

    def update(self, id_, **fields) -> ModelT | None:
        with self._session_factory() as db:
            obj = db.get(self.model, id_)
            if obj is None:
                return None
            changed_by = fields.get("updated_by")
            for column, value in fields.items():
                if column in _SKIP_AUDIT_FIELDS:
                    setattr(obj, column, value)
                    continue
                old_value = getattr(obj, column)
                setattr(obj, column, value)
                if old_value != value:
                    _write_audit(db, obj, "UPDATE", changed_by, column, old_value, value)
            db.commit()
            db.refresh(obj)
            return obj

    def delete(self, id_) -> None:
        with self._session_factory() as db:
            obj = db.get(self.model, id_)
            if obj is not None:
                _write_audit(db, obj, "DELETE", getattr(obj, "updated_by", None))
                db.delete(obj)
                db.commit()

    def update_if(self, id_, *, expected: dict, **fields) -> ModelT | None:
        """Conditional update guarded by a row lock (SELECT ... FOR UPDATE),
        for callers that must not blindly clobber a row another transaction
        might be racing to change (e.g. two callers both trying to be the
        one to transition a PENDING task to DONE/SKIPPED — see
        crm_service.complete_cadence_task() / advance_due_cadence_steps()).

        Locks the row for the life of this transaction, re-checks every
        (column, value) pair in `expected` against what's actually in the
        database right now, and only then applies `fields` — same
        audit-on-change behavior as update() above. A concurrent second
        caller trying the same thing blocks on the lock until the first
        commits, then re-reads the now-changed row, finds `expected` no
        longer matches, and gets None back having applied nothing — the
        same "someone else already handled this" signal a fresh read would
        give it, just race-free. Returns None immediately (no lock held
        past the read) if the row doesn't exist or `expected` doesn't match.
        """
        with self._session_factory() as db:
            stmt = select(self.model).where(self.model.id == id_).with_for_update()
            obj = db.execute(stmt).scalar_one_or_none()
            if obj is None:
                return None
            for column, value in expected.items():
                if getattr(obj, column) != value:
                    return None
            changed_by = fields.get("updated_by")
            for column, value in fields.items():
                if column in _SKIP_AUDIT_FIELDS:
                    setattr(obj, column, value)
                    continue
                old_value = getattr(obj, column)
                setattr(obj, column, value)
                if old_value != value:
                    _write_audit(db, obj, "UPDATE", changed_by, column, old_value, value)
            db.commit()
            db.refresh(obj)
            return obj


class SoftDeleteCrudRepository(CrudRepository[ModelT]):
    """Same as CrudRepository, but list()/get() hide soft-deleted rows and
    delete() stamps deleted_at instead of removing the row. Use for any
    model built on models.base.SoftDeleteMixin."""

    def list(self, **filters) -> list[ModelT]:
        with self._session_factory() as db:
            stmt = select(self.model).where(self.model.deleted_at.is_(None))
            for column, value in filters.items():
                stmt = stmt.where(getattr(self.model, column) == value)
            return list(db.execute(stmt).scalars().all())

    def get(self, id_) -> ModelT | None:
        with self._session_factory() as db:
            obj = db.get(self.model, id_)
            return obj if obj is not None and obj.deleted_at is None else None

    def delete(self, id_) -> None:
        with self._session_factory() as db:
            obj = db.get(self.model, id_)
            if obj is not None:
                _write_audit(db, obj, "SOFT_DELETE", getattr(obj, "updated_by", None))
                obj.deleted_at = datetime.now(timezone.utc)
                db.commit()

    def update_if(self, id_, *, expected: dict, **fields) -> ModelT | None:
        """Same row-locked conditional update as CrudRepository.update_if(),
        additionally treating a soft-deleted row as not found (mirrors
        get()/list() above)."""
        with self._session_factory() as db:
            stmt = (select(self.model)
                    .where(self.model.id == id_, self.model.deleted_at.is_(None))
                    .with_for_update())
            obj = db.execute(stmt).scalar_one_or_none()
            if obj is None:
                return None
            for column, value in expected.items():
                if getattr(obj, column) != value:
                    return None
            changed_by = fields.get("updated_by")
            for column, value in fields.items():
                if column in _SKIP_AUDIT_FIELDS:
                    setattr(obj, column, value)
                    continue
                old_value = getattr(obj, column)
                setattr(obj, column, value)
                if old_value != value:
                    _write_audit(db, obj, "UPDATE", changed_by, column, old_value, value)
            db.commit()
            db.refresh(obj)
            return obj


def next_business_id(db: Session, model: type, id_column: str, prefix: str,
                     width: int = 5) -> str:
    """Generate the next zero-padded business-format id, e.g. ACC-00042.

    Scans existing ids with the given prefix (any soft-deleted or live row)
    and returns prefix + max(existing numeric suffix) + 1. Used by the few
    modules whose primary key is a human-readable code rather than a UUID
    (account, agreement, opportunity, project) — call with an already-open
    session from within the owning repository's own method.
    """
    column = getattr(model, id_column)
    ids = db.execute(select(column)).scalars().all()
    nums = [int(i.split("-")[-1]) for i in ids if i.startswith(prefix)]
    return f"{prefix}{(max(nums) + 1) if nums else 1:0{width}d}"


def resolve_lookup_row(repo: CrudRepository, code: str, error_code: str, label: str,
                       status_code: int = 422, message: str | None = None):
    """Resolve a lookup-table `code` (account_type, agreement_status, role,
    ...) to its row, or raise a DomainError naming `label`. Every module used
    to hand-roll its own `list(code=...) then take rows[0]` version of this;
    shared here so there's exactly one place that does it. `resolve_lookup_id`
    below is the common case (id only); pass a full lookup repo + code here
    when the caller also needs other columns on the row (e.g.
    agreement_type.default_sla_hours)."""
    rows = repo.list(code=code.upper())
    if not rows:
        raise DomainError(error_code, message or f"Unknown {label} '{code}'.", status_code)
    return rows[0]


def resolve_lookup_id(repo: CrudRepository, code: str, error_code: str, label: str,
                      status_code: int = 422, message: str | None = None) -> int:
    """Same as resolve_lookup_row(), but returns just the row's id — the
    common case for every `_<x>_id(code)` helper across the service layer."""
    return resolve_lookup_row(repo, code, error_code, label, status_code, message).id
