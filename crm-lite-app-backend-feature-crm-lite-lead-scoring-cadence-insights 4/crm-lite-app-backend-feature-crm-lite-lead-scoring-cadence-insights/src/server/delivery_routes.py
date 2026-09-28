"""Delivery module routes (§1/§9 of the API spec) — 19 endpoints: SOW detail,
budget (versioned, incl. a bulk consumption endpoint across all SOWs),
rate-card, team, milestones, timesheets.

IMPLEMENTED — see services/delivery_service.py. All SOW sub-resources are
keyed off an agreement_id that is itself of type SOW (see contracts_routes.py).
"""
from uuid import UUID

from fastapi import APIRouter, Depends

from src.models import delivery_models
from src.repositories.contracts_repository import get_agreement_repository
from src.repositories.crm_repository import get_account_repository, get_opportunity_repository
from src.repositories.delivery_repository import (
    get_asset_repository,
    get_order_repository,
    get_revenue_recognition_entry_repository,
    get_sow_budget_repository,
    get_sow_detail_repository,
    get_sow_milestone_repository,
    get_sow_rate_card_repository,
    get_sow_team_member_repository,
    get_sow_timesheet_repository,
)
from src.repositories.project_repository import get_project_repository
from src.services import delivery_service
from src.utils.permissions import requires
from src.utils.security import CurrentUser

router = APIRouter(tags=["Delivery"])


# ---- SOW detail ----
@router.get("/agreements/{agreement_id}/sow-detail", response_model=delivery_models.SowDetailOut)
def get_sow_detail(agreement_id: str, u: CurrentUser = Depends(requires("platform.read")),
                   account_repo=Depends(get_account_repository),
                   agreement_repo=Depends(get_agreement_repository),
                   detail_repo=Depends(get_sow_detail_repository)):
    return delivery_service.get_sow_detail(u, account_repo, agreement_repo, detail_repo, agreement_id)


@router.patch("/agreements/{agreement_id}/sow-detail", response_model=delivery_models.SowDetailOut)
def update_sow_detail(agreement_id: str, payload: delivery_models.SowDetailUpsert,
                      u: CurrentUser = Depends(requires("sow.write")),
                      account_repo=Depends(get_account_repository),
                      agreement_repo=Depends(get_agreement_repository),
                      project_repo=Depends(get_project_repository),
                      detail_repo=Depends(get_sow_detail_repository)):
    return delivery_service.upsert_sow_detail(u, account_repo, agreement_repo, project_repo, detail_repo,
                                              agreement_id, payload)


# ---- Budget (versioned) ----
@router.get("/agreements/{agreement_id}/budget", response_model=delivery_models.SowBudgetOut)
def get_budget(agreement_id: str, u: CurrentUser = Depends(requires("platform.read")),
              account_repo=Depends(get_account_repository),
              agreement_repo=Depends(get_agreement_repository),
              budget_repo=Depends(get_sow_budget_repository)):
    return delivery_service.get_budget(u, account_repo, agreement_repo, budget_repo, agreement_id)


@router.post("/agreements/{agreement_id}/budget", status_code=201,
             response_model=delivery_models.SowBudgetOut)
def revise_budget(agreement_id: str, payload: delivery_models.SowBudgetRevise,
                  u: CurrentUser = Depends(requires("sow.write")),
                  account_repo=Depends(get_account_repository),
                  agreement_repo=Depends(get_agreement_repository),
                  budget_repo=Depends(get_sow_budget_repository),
                  detail_repo=Depends(get_sow_detail_repository)):
    return delivery_service.revise_budget(u, account_repo, agreement_repo, budget_repo, detail_repo,
                                          agreement_id, payload)


@router.get("/agreements/{agreement_id}/budget/consumption",
            response_model=delivery_models.SowBudgetConsumptionOut)
def get_budget_consumption(agreement_id: str, u: CurrentUser = Depends(requires("platform.read")),
                           account_repo=Depends(get_account_repository),
                           agreement_repo=Depends(get_agreement_repository),
                           budget_repo=Depends(get_sow_budget_repository),
                           team_repo=Depends(get_sow_team_member_repository),
                           rate_card_repo=Depends(get_sow_rate_card_repository),
                           timesheet_repo=Depends(get_sow_timesheet_repository)):
    return delivery_service.get_budget_consumption(
        u, account_repo, agreement_repo, budget_repo, team_repo, rate_card_repo,
        timesheet_repo, agreement_id)


@router.get("/sow-budget-consumption", response_model=list[delivery_models.SowBudgetConsumptionOut])
def list_budget_consumption(u: CurrentUser = Depends(requires("platform.read")),
                            account_repo=Depends(get_account_repository),
                            agreement_repo=Depends(get_agreement_repository),
                            budget_repo=Depends(get_sow_budget_repository),
                            team_repo=Depends(get_sow_team_member_repository),
                            rate_card_repo=Depends(get_sow_rate_card_repository),
                            timesheet_repo=Depends(get_sow_timesheet_repository)):
    return delivery_service.list_budget_consumption(
        u, account_repo, agreement_repo, budget_repo, team_repo, rate_card_repo, timesheet_repo)


# ---- Rate card ----
@router.get("/agreements/{agreement_id}/rate-card", response_model=list[delivery_models.SowRateCardOut])
def list_rate_card(agreement_id: str, u: CurrentUser = Depends(requires("platform.read")),
                   account_repo=Depends(get_account_repository),
                   agreement_repo=Depends(get_agreement_repository),
                   rate_card_repo=Depends(get_sow_rate_card_repository)):
    return delivery_service.list_rate_card(u, account_repo, agreement_repo, rate_card_repo, agreement_id)


@router.post("/agreements/{agreement_id}/rate-card", status_code=201,
             response_model=delivery_models.SowRateCardOut)
def add_rate_card_line(agreement_id: str, payload: delivery_models.SowRateCardCreate,
                       u: CurrentUser = Depends(requires("sow.write")),
                       account_repo=Depends(get_account_repository),
                       agreement_repo=Depends(get_agreement_repository),
                       rate_card_repo=Depends(get_sow_rate_card_repository),
                       detail_repo=Depends(get_sow_detail_repository)):
    return delivery_service.add_rate_card_line(u, account_repo, agreement_repo, rate_card_repo, detail_repo,
                                               agreement_id, payload)


@router.patch("/rate-card/{rate_id}", response_model=delivery_models.SowRateCardOut)
def update_rate_card_line(rate_id: UUID, payload: delivery_models.SowRateCardUpdate,
                         u: CurrentUser = Depends(requires("sow.write")),
                         account_repo=Depends(get_account_repository),
                         agreement_repo=Depends(get_agreement_repository),
                         rate_card_repo=Depends(get_sow_rate_card_repository)):
    return delivery_service.update_rate_card_line(u, account_repo, agreement_repo, rate_card_repo, rate_id, payload)


# ---- Team ----
@router.get("/agreements/{agreement_id}/team", response_model=list[delivery_models.SowTeamMemberOut])
def list_team(agreement_id: str, u: CurrentUser = Depends(requires("platform.read")),
             account_repo=Depends(get_account_repository),
             agreement_repo=Depends(get_agreement_repository),
             team_repo=Depends(get_sow_team_member_repository)):
    return delivery_service.list_team(u, account_repo, agreement_repo, team_repo, agreement_id)


@router.post("/agreements/{agreement_id}/team", status_code=201,
             response_model=delivery_models.SowTeamMemberOut)
def add_team_member(agreement_id: str, payload: delivery_models.SowTeamMemberCreate,
                    u: CurrentUser = Depends(requires("sow.write")),
                    account_repo=Depends(get_account_repository),
                    agreement_repo=Depends(get_agreement_repository),
                    team_repo=Depends(get_sow_team_member_repository),
                    detail_repo=Depends(get_sow_detail_repository)):
    return delivery_service.add_team_member(u, account_repo, agreement_repo, team_repo, detail_repo,
                                            agreement_id, payload)


@router.patch("/team-member/{member_id}", response_model=delivery_models.SowTeamMemberOut)
def update_team_member(member_id: UUID, payload: delivery_models.SowTeamMemberUpdate,
                       u: CurrentUser = Depends(requires("sow.write")),
                       account_repo=Depends(get_account_repository),
                       agreement_repo=Depends(get_agreement_repository),
                       team_repo=Depends(get_sow_team_member_repository)):
    return delivery_service.update_team_member(u, account_repo, agreement_repo, team_repo, member_id, payload)


# ---- Milestones ----
@router.get("/agreements/{agreement_id}/milestones", response_model=list[delivery_models.SowMilestoneOut])
def list_milestones(agreement_id: str, u: CurrentUser = Depends(requires("platform.read")),
                    account_repo=Depends(get_account_repository),
                    agreement_repo=Depends(get_agreement_repository),
                    milestone_repo=Depends(get_sow_milestone_repository)):
    return delivery_service.list_milestones(u, account_repo, agreement_repo, milestone_repo, agreement_id)


@router.post("/agreements/{agreement_id}/milestones", status_code=201,
             response_model=delivery_models.SowMilestoneOut)
def add_milestone(agreement_id: str, payload: delivery_models.SowMilestoneCreate,
                  u: CurrentUser = Depends(requires("sow.write")),
                  account_repo=Depends(get_account_repository),
                  agreement_repo=Depends(get_agreement_repository),
                  milestone_repo=Depends(get_sow_milestone_repository),
                  detail_repo=Depends(get_sow_detail_repository)):
    return delivery_service.add_milestone(u, account_repo, agreement_repo, milestone_repo, detail_repo,
                                          agreement_id, payload)


@router.patch("/milestones/{milestone_id}", response_model=delivery_models.SowMilestoneOut)
def update_milestone(milestone_id: UUID, payload: delivery_models.SowMilestoneUpdate,
                     u: CurrentUser = Depends(requires("sow.write")),
                     account_repo=Depends(get_account_repository),
                     agreement_repo=Depends(get_agreement_repository),
                     milestone_repo=Depends(get_sow_milestone_repository),
                     detail_repo=Depends(get_sow_detail_repository),
                     project_repo=Depends(get_project_repository),
                     opportunity_repo=Depends(get_opportunity_repository),
                     asset_repo=Depends(get_asset_repository),
                     order_repo=Depends(get_order_repository),
                     revenue_repo=Depends(get_revenue_recognition_entry_repository)):
    return delivery_service.update_milestone(u, account_repo, agreement_repo, milestone_repo,
                                             milestone_id, payload, detail_repo, project_repo,
                                             opportunity_repo, asset_repo, order_repo, revenue_repo)


# ---- Assets, Orders & Revenue Recognition (read-only — see delivery_service.py) ----
@router.get("/accounts/{account_id}/assets", response_model=list[delivery_models.AssetOut])
def list_assets(account_id: str, u: CurrentUser = Depends(requires("platform.read")),
                account_repo=Depends(get_account_repository),
                asset_repo=Depends(get_asset_repository)):
    return delivery_service.list_assets_for_account(u, account_repo, asset_repo, account_id)


@router.get("/agreements/{agreement_id}/orders", response_model=list[delivery_models.OrderOut])
def list_orders(agreement_id: str, u: CurrentUser = Depends(requires("platform.read")),
                account_repo=Depends(get_account_repository),
                agreement_repo=Depends(get_agreement_repository),
                order_repo=Depends(get_order_repository)):
    return delivery_service.list_orders(u, account_repo, agreement_repo, order_repo, agreement_id)


@router.get("/agreements/{agreement_id}/revenue-recognition",
           response_model=list[delivery_models.RevenueRecognitionEntryOut])
def list_revenue_recognition(agreement_id: str, u: CurrentUser = Depends(requires("platform.read")),
                             account_repo=Depends(get_account_repository),
                             agreement_repo=Depends(get_agreement_repository),
                             revenue_repo=Depends(get_revenue_recognition_entry_repository)):
    return delivery_service.list_revenue_recognition(u, account_repo, agreement_repo, revenue_repo,
                                                      agreement_id)


# ---- Timesheets ----
@router.get("/timesheets", response_model=list[delivery_models.SowTimesheetOut])
def list_timesheets(u: CurrentUser = Depends(requires("timesheets.read")),
                    timesheet_repo=Depends(get_sow_timesheet_repository)):
    return delivery_service.list_timesheets(u, timesheet_repo)


@router.post("/timesheets", status_code=201, response_model=delivery_models.SowTimesheetOut)
def submit_timesheet(payload: delivery_models.SowTimesheetCreate,
                     u: CurrentUser = Depends(requires("timesheets.submit")),
                     team_repo=Depends(get_sow_team_member_repository),
                     timesheet_repo=Depends(get_sow_timesheet_repository)):
    return delivery_service.submit_timesheet(u, team_repo, timesheet_repo, payload)


@router.patch("/timesheets/{timesheet_id}", response_model=delivery_models.SowTimesheetOut)
def edit_timesheet(timesheet_id: UUID, payload: delivery_models.SowTimesheetUpdate,
                   u: CurrentUser = Depends(requires("timesheets.submit")),
                   timesheet_repo=Depends(get_sow_timesheet_repository)):
    return delivery_service.edit_timesheet(u, timesheet_repo, timesheet_id, payload)


@router.patch("/timesheets/{timesheet_id}/approve", response_model=delivery_models.SowTimesheetOut)
def approve_timesheet(timesheet_id: UUID, u: CurrentUser = Depends(requires("timesheets.approve")),
                      timesheet_repo=Depends(get_sow_timesheet_repository)):
    return delivery_service.approve_timesheet(u, timesheet_repo, timesheet_id)


@router.patch("/timesheets/{timesheet_id}/reject", response_model=delivery_models.SowTimesheetOut)
def reject_timesheet(timesheet_id: UUID, u: CurrentUser = Depends(requires("timesheets.approve")),
                     timesheet_repo=Depends(get_sow_timesheet_repository)):
    return delivery_service.reject_timesheet(u, timesheet_repo, timesheet_id)
