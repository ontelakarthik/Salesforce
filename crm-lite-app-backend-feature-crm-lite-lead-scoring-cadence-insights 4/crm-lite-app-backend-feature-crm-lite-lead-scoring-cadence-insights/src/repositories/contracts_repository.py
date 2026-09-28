"""Contracts module repositories (§1/§8 of the API spec) — real, Postgres-
backed data access for every table this module owns. This is the central
"database logic" layer: developers building contracts_service.py /
contracts_routes.py call these classes directly and never open a Session
themselves.

Tables covered: agreement_type (lookup), agreement_status (lookup),
agreement, agreement_document, agreement_clause, agreement_review.
SOW-specific sub-resources (sow_detail, sow_budget, ...) live in
repositories/delivery_repository.py since Delivery is a separate service.
"""
from functools import lru_cache

from sqlalchemy import select

from src.models.contracts_models import (
    Agreement,
    AgreementClause,
    AgreementDocument,
    AgreementNote,
    AgreementReview,
    AgreementStatus,
    AgreementType,
)
from src.repositories._base import CrudRepository, SoftDeleteCrudRepository, next_business_id


class AgreementTypeRepository(CrudRepository[AgreementType]):
    model = AgreementType


class AgreementStatusRepository(CrudRepository[AgreementStatus]):
    model = AgreementStatus


class AgreementRepository(SoftDeleteCrudRepository[Agreement]):
    model = Agreement

    def next_id(self, prefix: str = "AGR-") -> str:
        with self._session_factory() as db:
            return next_business_id(db, Agreement, "id", prefix)

    def list_for_account(self, account_id: str) -> list[Agreement]:
        return self.list(account_id=account_id)

    def has_signed_sow(self, account_id: str) -> bool:
        """True if the account has >= 1 SOW-type agreement in SIGNED status.
        Handy for the CRM module's promote-to-CLIENT rule."""
        with self._session_factory() as db:
            stmt = (
                select(Agreement.id)
                .join(AgreementType, Agreement.agreement_type_id == AgreementType.id)
                .join(AgreementStatus, Agreement.agreement_status_id == AgreementStatus.id)
                .where(
                    Agreement.account_id == account_id,
                    Agreement.deleted_at.is_(None),
                    AgreementType.code == "SOW",
                    AgreementStatus.code == "SIGNED",
                )
                .limit(1)
            )
            return db.execute(stmt).first() is not None

    def count_active_for_account(self, account_id: str) -> int:
        """Agreements not yet EXPIRED/SUPERSEDED (terminal) for this account.
        Handy for the CRM module's delete-blocked-by-dependents rule."""
        with self._session_factory() as db:
            stmt = (
                select(Agreement.id)
                .join(AgreementStatus, Agreement.agreement_status_id == AgreementStatus.id)
                .where(
                    Agreement.account_id == account_id,
                    Agreement.deleted_at.is_(None),
                    AgreementStatus.is_terminal.is_(False),
                )
            )
            return len(db.execute(stmt).all())


class AgreementDocumentRepository(SoftDeleteCrudRepository[AgreementDocument]):
    model = AgreementDocument

    def list_for_agreement(self, agreement_id: str) -> list[AgreementDocument]:
        return self.list(agreement_id=agreement_id)


class AgreementClauseRepository(SoftDeleteCrudRepository[AgreementClause]):
    model = AgreementClause

    def list_for_agreement(self, agreement_id: str) -> list[AgreementClause]:
        return self.list(agreement_id=agreement_id)


class AgreementReviewRepository(SoftDeleteCrudRepository[AgreementReview]):
    model = AgreementReview

    def list_for_agreement(self, agreement_id: str) -> list[AgreementReview]:
        return self.list(agreement_id=agreement_id)


class AgreementNoteRepository(SoftDeleteCrudRepository[AgreementNote]):
    model = AgreementNote

    def list_for_agreement(self, agreement_id: str) -> list[AgreementNote]:
        return self.list(agreement_id=agreement_id)


@lru_cache(maxsize=1)
def get_agreement_type_repository() -> AgreementTypeRepository:
    return AgreementTypeRepository()


@lru_cache(maxsize=1)
def get_agreement_status_repository() -> AgreementStatusRepository:
    return AgreementStatusRepository()


@lru_cache(maxsize=1)
def get_agreement_repository() -> AgreementRepository:
    return AgreementRepository()


@lru_cache(maxsize=1)
def get_agreement_document_repository() -> AgreementDocumentRepository:
    return AgreementDocumentRepository()


@lru_cache(maxsize=1)
def get_agreement_clause_repository() -> AgreementClauseRepository:
    return AgreementClauseRepository()


@lru_cache(maxsize=1)
def get_agreement_review_repository() -> AgreementReviewRepository:
    return AgreementReviewRepository()


@lru_cache(maxsize=1)
def get_agreement_note_repository() -> AgreementNoteRepository:
    return AgreementNoteRepository()
