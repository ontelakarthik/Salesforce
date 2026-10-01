"""Project module business logic (§1/§7 of the API spec) — Projects + SOW
rollups. IMPLEMENTED.

Rules enforced:
- create        : opportunity must exist and be in stage WON; project starts
                  in PLANNING; account_id is inherited from the opportunity.
- create/update : target_end_date must be >= start_date when both are set.
- delete        : blocked while the project has a non-terminal (active) SOW
                  linked via sow_detail.project_id.
- create_project_sow: composes contracts_service.create_agreement (type=SOW)
                  with delivery_service.upsert_sow_detail (project linkage) so
                  callers get a ready-to-use SOW in one request.

Depends only on repository classes plus contracts_service/delivery_service
(reused for agreement/sow-detail creation, not reimplemented here) — never on
a SQLAlchemy Session directly.
"""
from src.models import contracts_models, delivery_models, project_models
from src.models.enums import OpportunityStage
from src.repositories._base import resolve_lookup_id
from src.repositories.contracts_repository import (
    AgreementNoteRepository,
    AgreementRepository,
    get_agreement_status_repository,
)
from src.repositories.crm_repository import (
    AccountRepository,
    OpportunityRepository,
    get_opportunity_stage_repository,
)
from src.repositories.delivery_repository import SowDetailRepository
from src.repositories.project_repository import ProjectRepository, get_project_status_repository
from src.services import contracts_service, delivery_service
from src.utils.error_handling import handle_errors
from src.utils.exceptions import DomainError
from src.utils.scope import owned_account_ids, require_account_scope
from src.utils.security import CurrentUser


def _status_id(code: str) -> int:
    return resolve_lookup_id(get_project_status_repository(), code, "PROJECT_STATUS_NOT_FOUND", "status")


def _project_status_map() -> dict[int, str]:
    """{project_status.id: code}, built once per list/mapper call rather than
    once per row — project_status is a handful of seeded rows."""
    return {s.id: s.code for s in get_project_status_repository().list()}


def _out(row, status_map: dict[int, str] | None = None) -> project_models.ProjectOut:
    codes = status_map if status_map is not None else _project_status_map()
    return project_models.ProjectOut(
        id=row.id, account_id=row.account_id, opportunity_id=row.opportunity_id,
        name=row.name, description=row.description, status=codes[row.project_status_id],
        account_executive_employee_id=row.account_executive_employee_id,
        start_date=row.start_date, target_end_date=row.target_end_date,
        actual_end_date=row.actual_end_date,
        created_at=row.created_at, updated_at=row.updated_at,
        created_by=row.created_by, updated_by=row.updated_by,
    )


def _get_or_404(repo: ProjectRepository, pid: str):
    row = repo.get(pid)
    if row is None:
        raise DomainError("PROJECT_NOT_FOUND", f"No project '{pid}'.", 404)
    return row


def _validate_dates(start_date, target_end_date) -> None:
    if start_date and target_end_date and target_end_date < start_date:
        raise DomainError("INVALID_DATE_RANGE", "target_end_date must be >= start_date.", 422)


@handle_errors("list projects")
def list_projects(user: CurrentUser, account_repo: AccountRepository,
                  repo: ProjectRepository) -> list[project_models.ProjectOut]:
    status_map = _project_status_map()
    owned = owned_account_ids(user, account_repo)
    rows = [r for r in repo.list() if owned is None or r.account_id in owned]
    return [_out(r, status_map) for r in sorted(rows, key=lambda r: r.id)]


@handle_errors("get project")
def get_project(user: CurrentUser, account_repo: AccountRepository,
                repo: ProjectRepository, pid: str) -> project_models.ProjectOut:
    row = _get_or_404(repo, pid)
    require_account_scope(user, account_repo, row.account_id, "Project is outside your data scope.")
    return _out(row)


@handle_errors("create project")
def create_project(user: CurrentUser, opportunity_repo: OpportunityRepository,
                   repo: ProjectRepository,
                   payload: project_models.ProjectCreate) -> project_models.ProjectOut:
    opportunity = opportunity_repo.get(payload.opportunity_id)
    if opportunity is None:
        raise DomainError("OPPORTUNITY_NOT_FOUND", f"No opportunity '{payload.opportunity_id}'.", 404)
    stage = get_opportunity_stage_repository().get(opportunity.opportunity_stage_id)
    if stage.code != OpportunityStage.WON.value:
        raise DomainError(
            "OPPORTUNITY_NOT_WON",
            "A project can only be created from a WON opportunity.", 422)
    _validate_dates(payload.start_date, payload.target_end_date)
    new_id = repo.next_id()
    row = repo.create(
        id=new_id, account_id=opportunity.account_id, opportunity_id=opportunity.id,
        name=payload.name, description=payload.description,
        project_status_id=_status_id("PLANNING"),
        account_executive_employee_id=payload.account_executive_employee_id,
        start_date=payload.start_date, target_end_date=payload.target_end_date,
        created_by=user.employee_id, updated_by=user.employee_id,
    )
    return _out(row)


@handle_errors("update project")
def update_project(user: CurrentUser, account_repo: AccountRepository, repo: ProjectRepository, pid: str,
                   payload: project_models.ProjectUpdate) -> project_models.ProjectOut:
    row = _get_or_404(repo, pid)
    require_account_scope(user, account_repo, row.account_id, "Project is outside your data scope.",
                          for_write=True)
    _validate_dates(row.start_date, payload.target_end_date or row.target_end_date)
    changes = payload.model_dump(exclude_unset=True)
    if "status" in changes:
        changes["project_status_id"] = _status_id(changes.pop("status"))
    changes["updated_by"] = user.employee_id
    updated = repo.update(pid, **changes)
    return _out(updated)


@handle_errors("delete project")
def delete_project(user: CurrentUser, account_repo: AccountRepository, repo: ProjectRepository,
                   agreement_repo: AgreementRepository,
                   detail_repo: SowDetailRepository, pid: str) -> None:
    row = _get_or_404(repo, pid)
    require_account_scope(user, account_repo, row.account_id, "Project is outside your data scope.",
                          for_write=True)
    for detail in detail_repo.list(project_id=pid):
        agreement = agreement_repo.get(detail.agreement_id)
        if agreement is None:
            continue
        status = get_agreement_status_repository().get(agreement.agreement_status_id)
        if not status.is_terminal:
            raise DomainError(
                "PROJECT_HAS_ACTIVE_SOW",
                f"Cannot delete: SOW '{agreement.id}' is still {status.code}.", 409)
    repo.delete(pid)


# --- Project <-> SOW linkage ----------------------------------------------------
@handle_errors("list the project's SOWs")
def list_project_sows(user: CurrentUser, account_repo: AccountRepository,
                      repo: ProjectRepository, agreement_repo: AgreementRepository,
                      detail_repo: SowDetailRepository, pid: str,
                      ) -> list[project_models.ProjectSowOut]:
    project = _get_or_404(repo, pid)
    require_account_scope(user, account_repo, project.account_id, "Project is outside your data scope.")
    out = []
    for detail in sorted(detail_repo.list(project_id=pid), key=lambda d: d.agreement_id):
        agreement = agreement_repo.get(detail.agreement_id)
        if agreement is None:
            # Soft-deleted agreement whose sow_detail row is still around —
            # skip it rather than crashing on a null mapper input.
            continue
        out.append(project_models.ProjectSowOut(
            agreement=contracts_service.agreement_out(agreement),
            sow_detail=delivery_models.SowDetailOut.model_validate(detail),
        ))
    return out


@handle_errors("add the SOW to the project")
def create_project_sow(user: CurrentUser, project_repo: ProjectRepository,
                       account_repo, agreement_repo: AgreementRepository,
                       detail_repo: SowDetailRepository, note_repo: AgreementNoteRepository,
                       pid: str, payload: project_models.ProjectSowCreate,
                       ) -> project_models.ProjectSowOut:
    project = _get_or_404(project_repo, pid)
    require_account_scope(user, account_repo, project.account_id, "Project is outside your data scope.",
                          for_write=True)
    new_agreement_out = contracts_service.create_agreement(
        user, account_repo, agreement_repo,
        contracts_models.AgreementCreate(
            account_id=project.account_id, agreement_type="SOW", title=payload.title,
            effective_date=payload.effective_date, expiry_date=payload.expiry_date,
        ),
    )
    detail_out = delivery_service.upsert_sow_detail(
        user, account_repo, agreement_repo, project_repo, detail_repo, new_agreement_out.id,
        delivery_models.SowDetailUpsert(
            project_id=pid, governing_msa_id=payload.governing_msa_id,
            billing_model=payload.billing_model, total_value=payload.total_value,
            currency=payload.currency, headcount=payload.headcount,
            invoicing_frequency=payload.invoicing_frequency,
        ),
    )
    if payload.notes:
        # AgreementCreate has no `notes` field (an agreement's notes are a
        # separate, append-only AgreementNote collection) — wire the
        # caller-supplied text through as a real note instead of silently
        # discarding it.
        contracts_service.add_note(
            user, account_repo, agreement_repo, note_repo, new_agreement_out.id,
            contracts_models.AgreementNoteCreate(note_text=payload.notes),
        )
    return project_models.ProjectSowOut(agreement=new_agreement_out, sow_detail=detail_out)
