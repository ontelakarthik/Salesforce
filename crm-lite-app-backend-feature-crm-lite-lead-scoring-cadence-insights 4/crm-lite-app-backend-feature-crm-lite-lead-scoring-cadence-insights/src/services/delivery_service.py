"""Delivery module business logic (§1/§9/§10 of the API spec) — SOW detail,
budget, rate card, team, milestones, and timesheets. IMPLEMENTED.

Rules enforced:
- sow-detail   : agreement must be of type SOW; project_id and governing_msa_id
                 (an MSA-type agreement) must exist; PK is the agreement id
                 itself, so upsert = create-if-absent else update.
- budget       : versioned — revise() inserts a new row (reason required),
                 flips the previous current row's is_current to False.
- team member  : exactly one of employee_id/external_name (also a DB check
                 constraint — see models/delivery_models.py).
- timesheets   : one entry per team member per week (duplicate SUBMITTED/
                 APPROVED blocked); week_start_date must be a Monday;
                 0 < hours <= 168; submitted_by/approved_by require a real
                 employee uuid (columns are NOT NULL/FK); a member can't
                 approve their own submission; edits only allowed while
                 SUBMITTED.

Depends only on repository classes — never on a SQLAlchemy Session directly.
"""
from datetime import datetime, timezone
from uuid import UUID

from src.models import delivery_models
from src.models.enums import TimesheetStatus
from src.repositories.contracts_repository import AgreementRepository, get_agreement_type_repository
from src.repositories.crm_repository import AccountRepository, OpportunityRepository
from src.repositories.delivery_repository import (
    AssetRepository,
    OrderRepository,
    RevenueRecognitionEntryRepository,
    SowBudgetRepository,
    SowDetailRepository,
    SowMilestoneRepository,
    SowRateCardRepository,
    SowTeamMemberRepository,
    SowTimesheetRepository,
)
from src.repositories.project_repository import ProjectRepository
from src.services.admin_service import verified_employee_uuid
from src.utils.error_handling import handle_errors
from src.utils.exceptions import DomainError
from src.utils.scope import owned_account_ids, require_account_scope
from src.utils.security import CurrentUser

_MAX_WEEKLY_HOURS = 168
_CLOSED_TIMESHEET_STATUSES = {TimesheetStatus.APPROVED.value, TimesheetStatus.REJECTED.value}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_sow_agreement(agreement_repo: AgreementRepository, aid: str):
    agreement = agreement_repo.get(aid)
    if agreement is None:
        raise DomainError("AGREEMENT_NOT_FOUND", f"No agreement '{aid}'.", 404)
    atype = get_agreement_type_repository().get(agreement.agreement_type_id)
    if atype.code != "SOW":
        raise DomainError("NOT_A_SOW", f"Agreement '{aid}' is not a SOW.", 422)
    return agreement


def _require_msa_agreement(agreement_repo: AgreementRepository, aid: str):
    agreement = agreement_repo.get(aid)
    if agreement is None:
        raise DomainError("GOVERNING_MSA_NOT_FOUND", f"No agreement '{aid}'.", 404)
    atype = get_agreement_type_repository().get(agreement.agreement_type_id)
    if atype.code != "MSA":
        raise DomainError("GOVERNING_MSA_INVALID", f"Agreement '{aid}' is not an MSA.", 422)
    return agreement


def _require_sow_detail_exists(detail_repo: SowDetailRepository, aid: str) -> None:
    """Budget/rate-card/team/milestones only make sense once the SOW's own
    project + governing MSA are on file — closes the gap where a bare SOW
    with no sow_detail row could otherwise accept a full budget and team."""
    if detail_repo.get(aid) is None:
        raise DomainError(
            "SOW_DETAIL_REQUIRED",
            "Set this SOW's project and governing MSA (Details tab) before adding budget, rate cards, team members, or milestones.",
            422)


# --- SOW detail ------------------------------------------------------------
@handle_errors("load the SOW details")
def get_sow_detail(user: CurrentUser, account_repo: AccountRepository,
                   agreement_repo: AgreementRepository, detail_repo: SowDetailRepository,
                   aid: str) -> delivery_models.SowDetailOut:
    agreement = _require_sow_agreement(agreement_repo, aid)
    require_account_scope(user, account_repo, agreement.account_id, "SOW is outside your data scope.")
    row = detail_repo.get(aid)
    if row is None:
        raise DomainError("SOW_DETAIL_NOT_FOUND", f"No sow-detail for agreement '{aid}'.", 404)
    return delivery_models.SowDetailOut.model_validate(row)


@handle_errors("save the SOW details")
def upsert_sow_detail(user: CurrentUser, account_repo: AccountRepository, agreement_repo: AgreementRepository,
                      project_repo: ProjectRepository, detail_repo: SowDetailRepository,
                      aid: str, payload: delivery_models.SowDetailUpsert,
                      ) -> delivery_models.SowDetailOut:
    sow_agreement = _require_sow_agreement(agreement_repo, aid)
    require_account_scope(user, account_repo, sow_agreement.account_id, "SOW is outside your data scope.",
                          for_write=True)
    project = project_repo.get(payload.project_id)
    if project is None:
        raise DomainError("PROJECT_NOT_FOUND", f"No project '{payload.project_id}'.", 404)
    if project.account_id != sow_agreement.account_id:
        raise DomainError(
            "PROJECT_ACCOUNT_MISMATCH",
            f"Project '{payload.project_id}' belongs to a different account than this SOW.", 422)
    msa = _require_msa_agreement(agreement_repo, payload.governing_msa_id)
    if msa.account_id != sow_agreement.account_id:
        raise DomainError(
            "GOVERNING_MSA_ACCOUNT_MISMATCH",
            f"Agreement '{payload.governing_msa_id}' belongs to a different account than this SOW.", 422)
    fields = dict(
        project_id=payload.project_id, governing_msa_id=payload.governing_msa_id,
        billing_model=payload.billing_model, total_value=payload.total_value,
        currency=payload.currency, headcount=payload.headcount,
        invoicing_frequency=payload.invoicing_frequency,
    )
    existing = detail_repo.get(aid)
    if existing is None:
        row = detail_repo.create(agreement_id=aid, created_by=user.employee_id,
                                 updated_by=user.employee_id, **fields)
    else:
        row = detail_repo.update(aid, updated_by=user.employee_id, **fields)
    return delivery_models.SowDetailOut.model_validate(row)


# --- Budget (versioned) ------------------------------------------------------
@handle_errors("get budget")
def get_budget(user: CurrentUser, account_repo: AccountRepository,
              agreement_repo: AgreementRepository, budget_repo: SowBudgetRepository,
              aid: str) -> delivery_models.SowBudgetOut:
    agreement = _require_sow_agreement(agreement_repo, aid)
    require_account_scope(user, account_repo, agreement.account_id, "SOW is outside your data scope.")
    row = budget_repo.get_current_for_agreement(aid)
    if row is None:
        raise DomainError("BUDGET_NOT_FOUND", f"No budget set for agreement '{aid}'.", 404)
    return delivery_models.SowBudgetOut.model_validate(row)


@handle_errors("revise budget")
def revise_budget(user: CurrentUser, account_repo: AccountRepository, agreement_repo: AgreementRepository,
                  budget_repo: SowBudgetRepository, detail_repo: SowDetailRepository, aid: str,
                  payload: delivery_models.SowBudgetRevise) -> delivery_models.SowBudgetOut:
    agreement = _require_sow_agreement(agreement_repo, aid)
    require_account_scope(user, account_repo, agreement.account_id, "SOW is outside your data scope.",
                          for_write=True)
    _require_sow_detail_exists(detail_repo, aid)
    current = budget_repo.get_current_for_agreement(aid)
    if current is not None:
        budget_repo.update(current.id, is_current=False, updated_by=user.employee_id)
    row = budget_repo.create(
        agreement_id=aid, amount=payload.amount, currency=payload.currency,
        alert_threshold_percents=payload.alert_threshold_percents,
        effective_from=payload.effective_from, is_current=True, reason=payload.reason,
        created_by=user.employee_id, updated_by=user.employee_id,
    )
    return delivery_models.SowBudgetOut.model_validate(row)


@handle_errors("load budget consumption")
def get_budget_consumption(user: CurrentUser, account_repo: AccountRepository,
                           agreement_repo: AgreementRepository, budget_repo: SowBudgetRepository,
                           team_repo: SowTeamMemberRepository, rate_card_repo: SowRateCardRepository,
                           timesheet_repo: SowTimesheetRepository,
                           aid: str) -> delivery_models.SowBudgetConsumptionOut:
    """Sums APPROVED timesheet hours x each team member's effective rate
    (override_rate_per_hour, else their rate card's rate_per_hour) — the
    aggregate the mock UI's "consumed"/"hours logged" numbers claimed to be
    but never actually were."""
    agreement = _require_sow_agreement(agreement_repo, aid)
    require_account_scope(user, account_repo, agreement.account_id, "SOW is outside your data scope.")
    budget = budget_repo.get_current_for_agreement(aid)
    team_by_id = {m.id: m for m in team_repo.list_for_agreement(aid)}
    rate_card_by_id = {rc.id: rc for rc in rate_card_repo.list_for_agreement(aid)}

    consumed = 0.0
    hours_logged = 0.0
    for ts in timesheet_repo.list_for_agreement(aid):
        if ts.status != TimesheetStatus.APPROVED.value:
            continue
        member = team_by_id.get(ts.sow_team_member_id)
        if member is None:
            continue
        rate = member.override_rate_per_hour
        if rate is None and member.rate_card_id is not None:
            rate_card = rate_card_by_id.get(member.rate_card_id)
            rate = rate_card.rate_per_hour if rate_card else None
        if rate is None:
            continue
        consumed += float(ts.hours) * float(rate)
        hours_logged += float(ts.hours)

    budget_amount = float(budget.amount) if budget else None
    consumed_percent = round(consumed / budget_amount * 100, 1) if budget_amount else None
    return delivery_models.SowBudgetConsumptionOut(
        agreement_id=aid, budget_amount=budget_amount, consumed=consumed,
        hours_logged=hours_logged, consumed_percent=consumed_percent,
    )


@handle_errors("load bulk budget consumption")
def list_budget_consumption(user: CurrentUser, account_repo: AccountRepository,
                            agreement_repo: AgreementRepository, budget_repo: SowBudgetRepository,
                            team_repo: SowTeamMemberRepository, rate_card_repo: SowRateCardRepository,
                            timesheet_repo: SowTimesheetRepository,
                            ) -> list[delivery_models.SowBudgetConsumptionOut]:
    """Same computation as get_budget_consumption(), across every SOW
    agreement in the caller's scope in one pass -- a handful of table scans
    instead of firing one HTTP request (and four DB round-trips) per SOW
    agreement, which is what the Dashboard used to do and stopped scaling
    once the SOW count grew past a handful."""
    owned = owned_account_ids(user, account_repo)
    type_map = {t.id: t.code for t in get_agreement_type_repository().list()}
    sow_agreements = [
        a for a in agreement_repo.list()
        if type_map.get(a.agreement_type_id) == "SOW" and (owned is None or a.account_id in owned)
    ]

    current_budget_by_agreement = {b.agreement_id: float(b.amount) for b in budget_repo.list() if b.is_current}
    team_by_id = {m.id: m for m in team_repo.list()}
    rate_card_by_id = {rc.id: rc for rc in rate_card_repo.list()}

    consumed_by_agreement: dict[str, float] = {}
    hours_by_agreement: dict[str, float] = {}
    for ts in timesheet_repo.list():
        if ts.status != TimesheetStatus.APPROVED.value:
            continue
        member = team_by_id.get(ts.sow_team_member_id)
        if member is None:
            continue
        rate = member.override_rate_per_hour
        if rate is None and member.rate_card_id is not None:
            rate_card = rate_card_by_id.get(member.rate_card_id)
            rate = rate_card.rate_per_hour if rate_card else None
        if rate is None:
            continue
        consumed_by_agreement[ts.agreement_id] = (
            consumed_by_agreement.get(ts.agreement_id, 0.0) + float(ts.hours) * float(rate))
        hours_by_agreement[ts.agreement_id] = (
            hours_by_agreement.get(ts.agreement_id, 0.0) + float(ts.hours))

    out = []
    for a in sow_agreements:
        budget_amount = current_budget_by_agreement.get(a.id)
        consumed = consumed_by_agreement.get(a.id, 0.0)
        hours_logged = hours_by_agreement.get(a.id, 0.0)
        consumed_percent = round(consumed / budget_amount * 100, 1) if budget_amount else None
        out.append(delivery_models.SowBudgetConsumptionOut(
            agreement_id=a.id, budget_amount=budget_amount, consumed=consumed,
            hours_logged=hours_logged, consumed_percent=consumed_percent,
        ))
    return out


# --- Rate card ---------------------------------------------------------------
@handle_errors("load the rate card")
def list_rate_card(user: CurrentUser, account_repo: AccountRepository,
                   agreement_repo: AgreementRepository, rate_card_repo: SowRateCardRepository,
                   aid: str) -> list[delivery_models.SowRateCardOut]:
    agreement = _require_sow_agreement(agreement_repo, aid)
    require_account_scope(user, account_repo, agreement.account_id, "SOW is outside your data scope.")
    rows = sorted(rate_card_repo.list_for_agreement(aid), key=lambda r: r.role_label)
    return [delivery_models.SowRateCardOut.model_validate(r) for r in rows]


@handle_errors("add the rate-card line")
def add_rate_card_line(user: CurrentUser, account_repo: AccountRepository, agreement_repo: AgreementRepository,
                       rate_card_repo: SowRateCardRepository, detail_repo: SowDetailRepository, aid: str,
                       payload: delivery_models.SowRateCardCreate) -> delivery_models.SowRateCardOut:
    agreement = _require_sow_agreement(agreement_repo, aid)
    require_account_scope(user, account_repo, agreement.account_id, "SOW is outside your data scope.",
                          for_write=True)
    _require_sow_detail_exists(detail_repo, aid)
    row = rate_card_repo.create(
        agreement_id=aid, role_label=payload.role_label, rate_per_hour=payload.rate_per_hour,
        currency=payload.currency, effective_from=payload.effective_from, notes=payload.notes,
        created_by=user.employee_id, updated_by=user.employee_id,
    )
    return delivery_models.SowRateCardOut.model_validate(row)


@handle_errors("update the rate-card line")
def update_rate_card_line(user: CurrentUser, account_repo: AccountRepository, agreement_repo: AgreementRepository,
                          rate_card_repo: SowRateCardRepository, rate_id: UUID,
                          payload: delivery_models.SowRateCardUpdate,
                          ) -> delivery_models.SowRateCardOut:
    rate_card = rate_card_repo.get(rate_id)
    if rate_card is None:
        raise DomainError("RATE_CARD_LINE_NOT_FOUND", f"No rate-card line '{rate_id}'.", 404)
    agreement = _require_sow_agreement(agreement_repo, rate_card.agreement_id)
    require_account_scope(user, account_repo, agreement.account_id, "SOW is outside your data scope.",
                          for_write=True)
    changes = payload.model_dump(exclude_unset=True)
    changes["updated_by"] = user.employee_id
    row = rate_card_repo.update(rate_id, **changes)
    return delivery_models.SowRateCardOut.model_validate(row)


# --- Team ----------------------------------------------------------------------
@handle_errors("list the SOW team")
def list_team(user: CurrentUser, account_repo: AccountRepository,
             agreement_repo: AgreementRepository, team_repo: SowTeamMemberRepository,
             aid: str) -> list[delivery_models.SowTeamMemberOut]:
    agreement = _require_sow_agreement(agreement_repo, aid)
    require_account_scope(user, account_repo, agreement.account_id, "SOW is outside your data scope.")
    rows = sorted(team_repo.list_for_agreement(aid), key=lambda r: r.assigned_from)
    return [delivery_models.SowTeamMemberOut.model_validate(r) for r in rows]


@handle_errors("add team member")
def add_team_member(user: CurrentUser, account_repo: AccountRepository, agreement_repo: AgreementRepository,
                    team_repo: SowTeamMemberRepository, detail_repo: SowDetailRepository, aid: str,
                    payload: delivery_models.SowTeamMemberCreate,
                    ) -> delivery_models.SowTeamMemberOut:
    agreement = _require_sow_agreement(agreement_repo, aid)
    require_account_scope(user, account_repo, agreement.account_id, "SOW is outside your data scope.",
                          for_write=True)
    _require_sow_detail_exists(detail_repo, aid)
    if (payload.employee_id is None) == (payload.external_name is None):
        raise DomainError("TEAM_MEMBER_TARGET_INVALID",
                          "Exactly one of employee_id or external_name must be set.", 422)
    row = team_repo.create(
        agreement_id=aid, employee_id=payload.employee_id, external_name=payload.external_name,
        rate_card_id=payload.rate_card_id, override_rate_per_hour=payload.override_rate_per_hour,
        assigned_from=payload.assigned_from, assigned_until=payload.assigned_until,
        created_by=user.employee_id, updated_by=user.employee_id,
    )
    return delivery_models.SowTeamMemberOut.model_validate(row)


@handle_errors("update team member")
def update_team_member(user: CurrentUser, account_repo: AccountRepository, agreement_repo: AgreementRepository,
                       team_repo: SowTeamMemberRepository, member_id: UUID,
                       payload: delivery_models.SowTeamMemberUpdate,
                       ) -> delivery_models.SowTeamMemberOut:
    member = team_repo.get(member_id)
    if member is None:
        raise DomainError("TEAM_MEMBER_NOT_FOUND", f"No team member '{member_id}'.", 404)
    agreement = _require_sow_agreement(agreement_repo, member.agreement_id)
    require_account_scope(user, account_repo, agreement.account_id, "SOW is outside your data scope.",
                          for_write=True)
    changes = payload.model_dump(exclude_unset=True)
    changes["updated_by"] = user.employee_id
    row = team_repo.update(member_id, **changes)
    return delivery_models.SowTeamMemberOut.model_validate(row)


# --- Milestones ------------------------------------------------------------------
@handle_errors("list milestones")
def list_milestones(user: CurrentUser, account_repo: AccountRepository,
                    agreement_repo: AgreementRepository, milestone_repo: SowMilestoneRepository,
                    aid: str) -> list[delivery_models.SowMilestoneOut]:
    agreement = _require_sow_agreement(agreement_repo, aid)
    require_account_scope(user, account_repo, agreement.account_id, "SOW is outside your data scope.")
    rows = sorted(milestone_repo.list_for_agreement(aid), key=lambda r: r.planned_date)
    return [delivery_models.SowMilestoneOut.model_validate(r) for r in rows]


@handle_errors("add milestone")
def add_milestone(user: CurrentUser, account_repo: AccountRepository, agreement_repo: AgreementRepository,
                  milestone_repo: SowMilestoneRepository, detail_repo: SowDetailRepository, aid: str,
                  payload: delivery_models.SowMilestoneCreate) -> delivery_models.SowMilestoneOut:
    agreement = _require_sow_agreement(agreement_repo, aid)
    require_account_scope(user, account_repo, agreement.account_id, "SOW is outside your data scope.",
                          for_write=True)
    _require_sow_detail_exists(detail_repo, aid)
    row = milestone_repo.create(
        agreement_id=aid, milestone_name=payload.milestone_name, planned_date=payload.planned_date,
        amount=payload.amount, status="PLANNED", notes=payload.notes,
        created_by=user.employee_id, updated_by=user.employee_id,
    )
    return delivery_models.SowMilestoneOut.model_validate(row)


#: Linear milestone lifecycle: DELAYED is a side-state reachable from either
#: of the two "in flight" stages, and resumes forward from there once
#: resolved. PAID is terminal.
_MILESTONE_TRANSITIONS: dict[str, set[str]] = {
    "PLANNED": {"DELIVERED", "DELAYED"},
    "DELIVERED": {"INVOICED", "DELAYED"},
    "DELAYED": {"DELIVERED", "INVOICED", "PAID"},
    "INVOICED": {"PAID"},
    "PAID": set(),
}


def _resolve_attribution(detail_repo: SowDetailRepository, project_repo: ProjectRepository,
                         opportunity_repo: OpportunityRepository, agreement_id: str,
                         ) -> tuple[str | None, UUID | None]:
    """Walk agreement (SOW) -> sow_detail.project_id -> project.opportunity_id
    -> opportunity.campaign_id, so a revenue recognition entry can be traced
    back to the campaign that originated it. Every hop is optional in
    practice (a project isn't required to have come from a Won opportunity)
    so this returns (None, None) rather than raising — an unattributed
    recognition entry is still a real number, just without a campaign to
    credit it to, which is itself an honest gap for deals that predate
    Campaign/Lead."""
    detail = detail_repo.get(agreement_id)
    if detail is None or detail.project_id is None:
        return None, None
    project = project_repo.get(detail.project_id)
    if project is None or project.opportunity_id is None:
        return None, None
    opportunity = opportunity_repo.get(project.opportunity_id)
    if opportunity is None:
        return project.opportunity_id, None
    return opportunity.id, opportunity.campaign_id


@handle_errors("update milestone")
def update_milestone(user: CurrentUser, account_repo: AccountRepository, agreement_repo: AgreementRepository,
                     milestone_repo: SowMilestoneRepository, milestone_id: UUID,
                     payload: delivery_models.SowMilestoneUpdate,
                     detail_repo: SowDetailRepository | None = None,
                     project_repo: ProjectRepository | None = None,
                     opportunity_repo: OpportunityRepository | None = None,
                     asset_repo: AssetRepository | None = None,
                     order_repo: OrderRepository | None = None,
                     revenue_repo: RevenueRecognitionEntryRepository | None = None,
                     ) -> delivery_models.SowMilestoneOut:
    """The six repos after `payload` are optional so every existing caller
    keeps working unchanged; they're only required to actually create the
    Asset/Order/RevenueRecognitionEntry side effect on an INVOICED transition
    (the route always passes all six — see delivery_routes.py)."""
    row = milestone_repo.get(milestone_id)
    if row is None:
        raise DomainError("MILESTONE_NOT_FOUND", f"No milestone '{milestone_id}'.", 404)
    agreement = _require_sow_agreement(agreement_repo, row.agreement_id)
    require_account_scope(user, account_repo, agreement.account_id, "SOW is outside your data scope.",
                          for_write=True)
    changes = payload.model_dump(exclude_unset=True)
    new_status = changes.get("status")
    if new_status is not None and new_status != row.status:
        allowed = _MILESTONE_TRANSITIONS.get(row.status, set())
        if new_status not in allowed:
            raise DomainError(
                "MILESTONE_STATUS_TRANSITION_INVALID",
                f"Cannot move a milestone from {row.status} to {new_status}.", 422)
        if new_status == "INVOICED":
            if not (payload.invoice_ref or "").strip():
                raise DomainError(
                    "INVOICE_REF_REQUIRED",
                    "An invoice reference is required when marking a milestone as invoiced.", 422)
            changes["invoiced_at"] = _now()
        if new_status == "DELIVERED" and changes.get("actual_date") is None:
            changes["actual_date"] = _now().date()
    changes["updated_by"] = user.employee_id
    row = milestone_repo.update(milestone_id, **changes)

    if (new_status == "INVOICED" and detail_repo is not None and project_repo is not None
            and opportunity_repo is not None and asset_repo is not None and order_repo is not None
            and revenue_repo is not None):
        _create_order_and_revenue(user, detail_repo, project_repo, opportunity_repo,
                                  asset_repo, order_repo, revenue_repo, agreement, row)

    return delivery_models.SowMilestoneOut.model_validate(row)


def _get_or_create_asset(user: CurrentUser, asset_repo: AssetRepository, agreement, campaign_id: UUID | None):
    """One Asset per SOW — the anchor Salesforce would call "what the account
    now owns." Created the first time any milestone on this SOW is invoiced;
    every later invoice reuses it rather than minting a duplicate, which is
    what makes it a stable thing a renewal Opportunity can point back at."""
    existing = asset_repo.get_for_agreement(agreement.id)
    if existing is not None:
        return existing
    return asset_repo.create(
        account_id=agreement.account_id, agreement_id=agreement.id, campaign_id=campaign_id,
        name=f"{agreement.title} — Delivered", status="ACTIVE",
        created_by=user.employee_id, updated_by=user.employee_id,
    )


def _create_order_and_revenue(user: CurrentUser, detail_repo: SowDetailRepository,
                              project_repo: ProjectRepository, opportunity_repo: OpportunityRepository,
                              asset_repo: AssetRepository, order_repo: OrderRepository,
                              revenue_repo: RevenueRecognitionEntryRepository,
                              agreement, milestone) -> None:
    """Side effect of a milestone reaching INVOICED — mirrors how contracts_
    service._notify() fires as a side effect of a status change elsewhere in
    this codebase, rather than requiring a second, separate write call. Order
    amount is the milestone's own amount; a milestone with no amount set
    produces no Order (there's nothing to recognize)."""
    if milestone.amount is None:
        return
    now = _now()
    opportunity_id, campaign_id = _resolve_attribution(detail_repo, project_repo, opportunity_repo, agreement.id)
    asset = _get_or_create_asset(user, asset_repo, agreement, campaign_id)
    order = order_repo.create(
        account_id=agreement.account_id, agreement_id=agreement.id, asset_id=asset.id,
        milestone_id=milestone.id, status="ACTIVATED", amount=milestone.amount, currency="USD",
        order_date=now.date(), created_by=user.employee_id, updated_by=user.employee_id,
    )
    revenue_repo.create(
        order_id=order.id, asset_id=asset.id, account_id=agreement.account_id, agreement_id=agreement.id,
        opportunity_id=opportunity_id, campaign_id=campaign_id,
        recognized_amount=milestone.amount, currency="USD", recognized_at=now,
        created_by=user.employee_id, updated_by=user.employee_id,
    )


# --- Timesheets --------------------------------------------------------------------
def _require_employee_uuid(user: CurrentUser) -> UUID:
    """submitted_by_employee_id/approved_by_employee_id are NOT NULL FKs to a
    real `employee` row — verified_employee_uuid() checks both that the
    header parses as a UUID and that it's a provisioned employee."""
    employee_uuid = verified_employee_uuid(user)
    if employee_uuid is None:
        raise DomainError(
            "NO_LINKED_EMPLOYEE",
            "Your gateway identity does not resolve to a provisioned employee record.", 422)
    return employee_uuid


def _validate_week_start(week_start_date) -> None:
    if week_start_date.weekday() != 0:  # Monday == 0
        raise DomainError("WEEK_START_NOT_MONDAY", "week_start_date must be a Monday.", 422)


def _validate_hours(hours: float) -> None:
    if not (0 < hours <= _MAX_WEEKLY_HOURS):
        raise DomainError("HOURS_OUT_OF_RANGE", f"hours must be > 0 and <= {_MAX_WEEKLY_HOURS}.", 422)


@handle_errors("list timesheets")
def list_timesheets(user: CurrentUser, timesheet_repo: SowTimesheetRepository,
                    ) -> list[delivery_models.SowTimesheetOut]:
    sees_all = user.has_capability("timesheets.approve")  # AE/ADMIN see all; others see own
    rows = timesheet_repo.list()
    if not sees_all:
        own = user.employee_uuid()
        rows = [r for r in rows if own is not None and r.submitted_by_employee_id == own]
    rows.sort(key=lambda r: r.week_start_date, reverse=True)
    return [delivery_models.SowTimesheetOut.model_validate(r) for r in rows]


@handle_errors("submit timesheet")
def submit_timesheet(user: CurrentUser, team_repo: SowTeamMemberRepository,
                     timesheet_repo: SowTimesheetRepository,
                     payload: delivery_models.SowTimesheetCreate,
                     ) -> delivery_models.SowTimesheetOut:
    if team_repo.get(payload.sow_team_member_id) is None:
        raise DomainError("TEAM_MEMBER_NOT_FOUND", f"No team member '{payload.sow_team_member_id}'.", 404)
    _validate_week_start(payload.week_start_date)
    _validate_hours(payload.hours)
    existing = [
        t for t in timesheet_repo.list_for_team_member(payload.sow_team_member_id)
        if t.week_start_date == payload.week_start_date and t.status != TimesheetStatus.REJECTED.value
    ]
    if existing:
        raise DomainError(
            "TIMESHEET_ALREADY_SUBMITTED",
            "A timesheet for this team member and week already exists.", 409)
    submitted_by = _require_employee_uuid(user)
    row = timesheet_repo.create(
        sow_team_member_id=payload.sow_team_member_id, agreement_id=payload.agreement_id,
        week_start_date=payload.week_start_date, hours=payload.hours,
        status=TimesheetStatus.SUBMITTED.value,
        submitted_by_employee_id=submitted_by, notes=payload.notes,
        created_by=user.employee_id, updated_by=user.employee_id,
    )
    return delivery_models.SowTimesheetOut.model_validate(row)


def _get_timesheet_or_404(timesheet_repo: SowTimesheetRepository, timesheet_id: UUID):
    row = timesheet_repo.get(timesheet_id)
    if row is None:
        raise DomainError("TIMESHEET_NOT_FOUND", f"No timesheet '{timesheet_id}'.", 404)
    return row


@handle_errors("edit timesheet")
def edit_timesheet(user: CurrentUser, timesheet_repo: SowTimesheetRepository, timesheet_id: UUID,
                   payload: delivery_models.SowTimesheetUpdate) -> delivery_models.SowTimesheetOut:
    row = _get_timesheet_or_404(timesheet_repo, timesheet_id)
    if row.status in _CLOSED_TIMESHEET_STATUSES:
        raise DomainError("TIMESHEET_CLOSED", f"Timesheet is already {row.status}.", 409)
    # timesheets.submit is held by SALES too, so without this check any
    # caller with that capability could edit anyone else's open timesheet by
    # id — approvers (AE/ADMIN) may still edit any row, matching the scope
    # list_timesheets() already applies for reads.
    if not user.has_capability("timesheets.approve") and row.submitted_by_employee_id != user.employee_uuid():
        raise DomainError("FORBIDDEN", "You can only edit your own timesheet.", 403)
    changes = payload.model_dump(exclude_unset=True)
    if "hours" in changes and changes["hours"] is not None:
        _validate_hours(changes["hours"])
    changes["updated_by"] = user.employee_id
    updated = timesheet_repo.update(timesheet_id, **changes)
    return delivery_models.SowTimesheetOut.model_validate(updated)


@handle_errors("approve timesheet")
def approve_timesheet(user: CurrentUser, timesheet_repo: SowTimesheetRepository,
                      timesheet_id: UUID) -> delivery_models.SowTimesheetOut:
    row = _get_timesheet_or_404(timesheet_repo, timesheet_id)
    if row.status in _CLOSED_TIMESHEET_STATUSES:
        raise DomainError("TIMESHEET_CLOSED", f"Timesheet is already {row.status}.", 409)
    approver = _require_employee_uuid(user)
    if row.submitted_by_employee_id == approver:
        raise DomainError("SELF_APPROVAL_FORBIDDEN", "You cannot approve your own timesheet.", 403)
    updated = timesheet_repo.update(
        timesheet_id, status=TimesheetStatus.APPROVED.value, approved_by_employee_id=approver,
        approved_at=_now(), updated_by=user.employee_id,
    )
    return delivery_models.SowTimesheetOut.model_validate(updated)


@handle_errors("reject timesheet")
def reject_timesheet(user: CurrentUser, timesheet_repo: SowTimesheetRepository,
                     timesheet_id: UUID) -> delivery_models.SowTimesheetOut:
    row = _get_timesheet_or_404(timesheet_repo, timesheet_id)
    if row.status in _CLOSED_TIMESHEET_STATUSES:
        raise DomainError("TIMESHEET_CLOSED", f"Timesheet is already {row.status}.", 409)
    approver = _require_employee_uuid(user)
    if row.submitted_by_employee_id == approver:
        raise DomainError("SELF_APPROVAL_FORBIDDEN", "You cannot reject your own timesheet.", 403)
    updated = timesheet_repo.update(
        timesheet_id, status=TimesheetStatus.REJECTED.value, approved_by_employee_id=approver,
        approved_at=_now(), updated_by=user.employee_id,
    )
    return delivery_models.SowTimesheetOut.model_validate(updated)


# --- Assets, Orders & Revenue Recognition -----------------------------------------
# Read-only from outside this module — all three are only ever written by
# update_milestone()'s INVOICED side effect (see _create_order_and_revenue()
# above), never through a public create endpoint.


@handle_errors("list assets")
def list_assets_for_account(user: CurrentUser, account_repo: AccountRepository,
                            asset_repo: AssetRepository, account_id: str) -> list[delivery_models.AssetOut]:
    if account_repo.get(account_id) is None:
        raise DomainError("ACCOUNT_NOT_FOUND", f"No account '{account_id}'.", 404)
    require_account_scope(user, account_repo, account_id, "Account is outside your data scope.")
    rows = asset_repo.list_for_account(account_id)
    return [delivery_models.AssetOut.model_validate(r) for r in rows]


@handle_errors("list orders")
def list_orders(user: CurrentUser, account_repo: AccountRepository, agreement_repo: AgreementRepository,
                order_repo: OrderRepository, aid: str) -> list[delivery_models.OrderOut]:
    agreement = _require_sow_agreement(agreement_repo, aid)
    require_account_scope(user, account_repo, agreement.account_id, "SOW is outside your data scope.")
    rows = sorted(order_repo.list_for_agreement(aid), key=lambda r: r.order_date)
    return [delivery_models.OrderOut.model_validate(r) for r in rows]


@handle_errors("list revenue recognition")
def list_revenue_recognition(user: CurrentUser, account_repo: AccountRepository,
                             agreement_repo: AgreementRepository,
                             revenue_repo: RevenueRecognitionEntryRepository,
                             aid: str) -> list[delivery_models.RevenueRecognitionEntryOut]:
    agreement = _require_sow_agreement(agreement_repo, aid)
    require_account_scope(user, account_repo, agreement.account_id, "SOW is outside your data scope.")
    rows = sorted(revenue_repo.list_for_agreement(aid), key=lambda r: r.recognized_at)
    return [delivery_models.RevenueRecognitionEntryOut.model_validate(r) for r in rows]
