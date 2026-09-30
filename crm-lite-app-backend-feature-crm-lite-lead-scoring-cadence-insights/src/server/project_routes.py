"""Project module routes (§1/§7 of the API spec) — 7 endpoints: Projects CRUD
+ project-SOW linkage.

IMPLEMENTED — see services/project_service.py.
"""
from fastapi import APIRouter, Depends

from src.models import project_models
from src.repositories.contracts_repository import get_agreement_note_repository, get_agreement_repository
from src.repositories.crm_repository import get_account_repository, get_opportunity_repository
from src.repositories.delivery_repository import get_sow_detail_repository
from src.repositories.project_repository import get_project_repository
from src.services import project_service
from src.utils.permissions import requires
from src.utils.security import CurrentUser

router = APIRouter(tags=["Project"])


# ---- Projects ----
@router.get("/projects", response_model=list[project_models.ProjectOut])
def list_projects(u: CurrentUser = Depends(requires("platform.read")),
                  account_repo=Depends(get_account_repository),
                  repo=Depends(get_project_repository)):
    return project_service.list_projects(u, account_repo, repo)


@router.post("/projects", status_code=201, response_model=project_models.ProjectOut)
def create_project(payload: project_models.ProjectCreate,
                   u: CurrentUser = Depends(requires("projects.write")),
                   opportunity_repo=Depends(get_opportunity_repository),
                   repo=Depends(get_project_repository)):
    return project_service.create_project(u, opportunity_repo, repo, payload)


@router.get("/projects/{project_id}", response_model=project_models.ProjectOut)
def get_project(project_id: str, u: CurrentUser = Depends(requires("platform.read")),
                account_repo=Depends(get_account_repository),
                repo=Depends(get_project_repository)):
    return project_service.get_project(u, account_repo, repo, project_id)


@router.patch("/projects/{project_id}", response_model=project_models.ProjectOut)
def update_project(project_id: str, payload: project_models.ProjectUpdate,
                   u: CurrentUser = Depends(requires("projects.write")),
                   account_repo=Depends(get_account_repository),
                   repo=Depends(get_project_repository)):
    return project_service.update_project(u, account_repo, repo, project_id, payload)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str, u: CurrentUser = Depends(requires("admin")),
                   account_repo=Depends(get_account_repository),
                   repo=Depends(get_project_repository),
                   agreement_repo=Depends(get_agreement_repository),
                   detail_repo=Depends(get_sow_detail_repository)):
    project_service.delete_project(u, account_repo, repo, agreement_repo, detail_repo, project_id)


# ---- Project <-> SOW linkage ----
@router.get("/projects/{project_id}/sows", response_model=list[project_models.ProjectSowOut])
def list_project_sows(project_id: str, u: CurrentUser = Depends(requires("platform.read")),
                      account_repo=Depends(get_account_repository),
                      repo=Depends(get_project_repository),
                      agreement_repo=Depends(get_agreement_repository),
                      detail_repo=Depends(get_sow_detail_repository)):
    return project_service.list_project_sows(u, account_repo, repo, agreement_repo, detail_repo, project_id)


@router.post("/projects/{project_id}/sows", status_code=201, response_model=project_models.ProjectSowOut)
def create_project_sow(project_id: str, payload: project_models.ProjectSowCreate,
                       u: CurrentUser = Depends(requires("projects.write")),
                       repo=Depends(get_project_repository),
                       account_repo=Depends(get_account_repository),
                       agreement_repo=Depends(get_agreement_repository),
                       detail_repo=Depends(get_sow_detail_repository),
                       note_repo=Depends(get_agreement_note_repository)):
    return project_service.create_project_sow(u, repo, account_repo, agreement_repo,
                                              detail_repo, note_repo, project_id, payload)
