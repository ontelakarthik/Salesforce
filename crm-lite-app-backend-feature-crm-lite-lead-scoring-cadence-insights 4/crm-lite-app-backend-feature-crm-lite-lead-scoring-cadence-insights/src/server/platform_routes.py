"""Platform module routes (§1/§12 of the API spec) — 4 endpoints: cross-cutting
reads (dashboard, search, lookups) + document upload URLs.

IMPLEMENTED — see services/platform_service.py. Employee/team admin lives in
admin_routes.py; auth/session + current-employee lives in auth_routes.py.
"""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from src.models import admin_models, platform_models
from src.repositories.activity_repository import get_communication_repository, get_notification_repository
from src.repositories.contracts_repository import get_agreement_repository
from src.repositories.crm_repository import (
    get_account_repository, get_cadence_task_repository, get_lead_cadence_enrollment_repository,
    get_lead_repository, get_opportunity_repository,
)
from src.repositories.delivery_repository import get_sow_timesheet_repository
from src.repositories.project_repository import get_project_repository
from src.services import platform_service
from src.utils.permissions import requires
from src.utils.security import CurrentUser, get_current_user

router = APIRouter(tags=["Platform"])


@router.get("/dashboard", response_model=platform_models.DashboardOut)
def dashboard(u: CurrentUser = Depends(requires("platform.read")),
             account_repo=Depends(get_account_repository),
             agreement_repo=Depends(get_agreement_repository),
             project_repo=Depends(get_project_repository),
             timesheet_repo=Depends(get_sow_timesheet_repository),
             notification_repo=Depends(get_notification_repository)):
    return platform_service.dashboard(u, account_repo, agreement_repo, project_repo,
                                      timesheet_repo, notification_repo)


@router.get("/manager-dashboard", response_model=platform_models.ManagerDashboardOut)
def manager_dashboard(
    campaign_id: UUID | None = Query(default=None),
    industry: str | None = Query(default=None),
    owner_employee_id: UUID | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    hot_lead_score_threshold: int = Query(default=50, ge=0),
    u: CurrentUser = Depends(requires("manager_dashboard.read")),
    lead_repo=Depends(get_lead_repository),
    comm_repo=Depends(get_communication_repository),
):
    return platform_service.manager_dashboard(
        u, lead_repo, comm_repo, campaign_id=campaign_id, industry=industry,
        owner_employee_id=owner_employee_id, date_from=date_from, date_to=date_to,
        hot_lead_score_threshold=hot_lead_score_threshold)


@router.get("/task-dashboard", response_model=platform_models.TaskDashboardOut)
def task_dashboard(u: CurrentUser = Depends(requires("manager_dashboard.read")),
                   lead_repo=Depends(get_lead_repository),
                   enrollment_repo=Depends(get_lead_cadence_enrollment_repository),
                   task_repo=Depends(get_cadence_task_repository)):
    return platform_service.task_dashboard(u, lead_repo, enrollment_repo, task_repo)


@router.get("/search", response_model=platform_models.SearchOut)
def search(q: str = Query(default=""), u: CurrentUser = Depends(requires("platform.read")),
          account_repo=Depends(get_account_repository),
          agreement_repo=Depends(get_agreement_repository),
          project_repo=Depends(get_project_repository),
          opportunity_repo=Depends(get_opportunity_repository)):
    return platform_service.search(u, q, account_repo, agreement_repo, project_repo, opportunity_repo)


@router.get("/lookups/{table}", response_model=list[admin_models.LookupOut])
def get_lookups(table: str, u: CurrentUser = Depends(requires("platform.read"))):
    return platform_service.get_lookups(table)


@router.post("/documents/upload-url", response_model=platform_models.UploadUrlOut)
def create_upload_url(payload: platform_models.UploadUrlCreate,
                      u: CurrentUser = Depends(get_current_user)):
    return platform_service.create_upload_url(payload)
