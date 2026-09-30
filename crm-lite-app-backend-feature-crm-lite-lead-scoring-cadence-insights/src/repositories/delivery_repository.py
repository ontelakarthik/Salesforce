"""Delivery module repositories (§1/§9/§10 of the API spec) — real, Postgres-
backed data access for every table this module owns. This is the central
"database logic" layer: developers building delivery_service.py /
delivery_routes.py call these classes directly and never open a Session
themselves.

Tables covered: sow_detail, sow_budget, sow_rate_card, sow_team_member,
sow_milestone, sow_timesheet. All key off agreement_id (a SOW is an
agreement subtype owned by the Contracts module — see contracts_models.py).
"""
from functools import lru_cache

from src.models.delivery_models import (
    Asset,
    Order,
    RevenueRecognitionEntry,
    SowBudget,
    SowDetail,
    SowMilestone,
    SowRateCard,
    SowTeamMember,
    SowTimesheet,
)
from src.repositories._base import CrudRepository, SoftDeleteCrudRepository


class SowDetailRepository(CrudRepository[SowDetail]):
    model = SowDetail  # PK is agreement_id — get()/delete() take the agreement id


class SowBudgetRepository(SoftDeleteCrudRepository[SowBudget]):
    model = SowBudget

    def list_for_agreement(self, agreement_id: str) -> list[SowBudget]:
        return self.list(agreement_id=agreement_id)

    def get_current_for_agreement(self, agreement_id: str) -> SowBudget | None:
        current = [b for b in self.list_for_agreement(agreement_id) if b.is_current]
        return current[0] if current else None


class SowRateCardRepository(SoftDeleteCrudRepository[SowRateCard]):
    model = SowRateCard

    def list_for_agreement(self, agreement_id: str) -> list[SowRateCard]:
        return self.list(agreement_id=agreement_id)


class SowTeamMemberRepository(SoftDeleteCrudRepository[SowTeamMember]):
    model = SowTeamMember

    def list_for_agreement(self, agreement_id: str) -> list[SowTeamMember]:
        return self.list(agreement_id=agreement_id)


class SowMilestoneRepository(SoftDeleteCrudRepository[SowMilestone]):
    model = SowMilestone

    def list_for_agreement(self, agreement_id: str) -> list[SowMilestone]:
        return self.list(agreement_id=agreement_id)


class SowTimesheetRepository(SoftDeleteCrudRepository[SowTimesheet]):
    model = SowTimesheet

    def list_for_agreement(self, agreement_id: str) -> list[SowTimesheet]:
        return self.list(agreement_id=agreement_id)

    def list_for_team_member(self, sow_team_member_id) -> list[SowTimesheet]:
        return self.list(sow_team_member_id=sow_team_member_id)


class AssetRepository(SoftDeleteCrudRepository[Asset]):
    model = Asset

    def get_for_agreement(self, agreement_id: str) -> Asset | None:
        rows = self.list(agreement_id=agreement_id)
        return rows[0] if rows else None

    def list_for_account(self, account_id: str) -> list[Asset]:
        return self.list(account_id=account_id)


class OrderRepository(SoftDeleteCrudRepository[Order]):
    model = Order

    def list_for_agreement(self, agreement_id: str) -> list[Order]:
        return self.list(agreement_id=agreement_id)

    def list_for_account(self, account_id: str) -> list[Order]:
        return self.list(account_id=account_id)


class RevenueRecognitionEntryRepository(SoftDeleteCrudRepository[RevenueRecognitionEntry]):
    model = RevenueRecognitionEntry

    def list_for_agreement(self, agreement_id: str) -> list[RevenueRecognitionEntry]:
        return self.list(agreement_id=agreement_id)

    def list_for_account(self, account_id: str) -> list[RevenueRecognitionEntry]:
        return self.list(account_id=account_id)


@lru_cache(maxsize=1)
def get_sow_detail_repository() -> SowDetailRepository:
    return SowDetailRepository()


@lru_cache(maxsize=1)
def get_sow_budget_repository() -> SowBudgetRepository:
    return SowBudgetRepository()


@lru_cache(maxsize=1)
def get_sow_rate_card_repository() -> SowRateCardRepository:
    return SowRateCardRepository()


@lru_cache(maxsize=1)
def get_sow_team_member_repository() -> SowTeamMemberRepository:
    return SowTeamMemberRepository()


@lru_cache(maxsize=1)
def get_sow_milestone_repository() -> SowMilestoneRepository:
    return SowMilestoneRepository()


@lru_cache(maxsize=1)
def get_sow_timesheet_repository() -> SowTimesheetRepository:
    return SowTimesheetRepository()


@lru_cache(maxsize=1)
def get_asset_repository() -> AssetRepository:
    return AssetRepository()


@lru_cache(maxsize=1)
def get_order_repository() -> OrderRepository:
    return OrderRepository()


@lru_cache(maxsize=1)
def get_revenue_recognition_entry_repository() -> RevenueRecognitionEntryRepository:
    return RevenueRecognitionEntryRepository()
