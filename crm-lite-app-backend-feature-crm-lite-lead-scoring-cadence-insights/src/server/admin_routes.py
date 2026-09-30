"""Admin module routes (§1/§11 of the API spec) — employees, employee
profile assignment, teams, admin-managed lookups, and Profile CRUD +
capability-matrix (admin-configurable RBAC, see utils/permissions.py).

IMPLEMENTED — see services/admin_service.py.
"""
from uuid import UUID

from fastapi import APIRouter, Depends

from src.models import admin_models
from src.services import admin_service
from src.services.email_client import get_optional_email_sender
from src.utils.permissions import requires
from src.utils.security import CurrentUser

router = APIRouter(tags=["Admin"])


@router.get("/admin/employees", response_model=list[admin_models.EmployeeOut])
def admin_list_employees(u: CurrentUser = Depends(requires("admin"))):
    return admin_service.list_employees()


# Deliberately NOT under /admin — every authenticated role needs this to
# resolve an owner/signer/reviewer id to a display name (Leads,
# Opportunities, SOWs, NDAs, Audit Log, ...), unlike the full employee
# record above, which is admin-only.
@router.get("/employees/directory", response_model=list[admin_models.EmployeeDirectoryEntry])
def employees_directory(u: CurrentUser = Depends(requires("platform.read"))):
    return admin_service.list_employee_directory()


@router.post("/admin/employees", status_code=201, response_model=admin_models.EmployeeCreateOut)
def admin_create_employee(payload: admin_models.EmployeeCreate,
                          u: CurrentUser = Depends(requires("admin")),
                          email_sender=Depends(get_optional_email_sender)):
    return admin_service.create_employee(u, email_sender, payload)


@router.patch("/admin/employees/{employee_id}", response_model=admin_models.EmployeeOut)
def admin_update_employee(employee_id: UUID, payload: admin_models.EmployeeUpdate,
                          u: CurrentUser = Depends(requires("admin"))):
    return admin_service.update_employee(u, employee_id, payload)


@router.put("/admin/employees/{employee_id}/profiles", response_model=admin_models.EmployeeOut)
def admin_set_employee_profiles(employee_id: UUID, payload: admin_models.EmployeeProfilesUpdate,
                                u: CurrentUser = Depends(requires("admin"))):
    return admin_service.set_employee_profiles(u, employee_id, payload)


@router.get("/admin/teams", response_model=list[admin_models.TeamOut])
def admin_list_teams(u: CurrentUser = Depends(requires("admin"))):
    return admin_service.list_teams()


@router.post("/admin/teams", status_code=201, response_model=admin_models.TeamOut)
def admin_create_team(payload: admin_models.TeamCreate, u: CurrentUser = Depends(requires("admin"))):
    return admin_service.create_team(u, payload)


@router.patch("/admin/teams/{team_id}", response_model=admin_models.TeamOut)
def admin_update_team(team_id: int, payload: admin_models.TeamUpdate,
                      u: CurrentUser = Depends(requires("admin"))):
    return admin_service.update_team(u, team_id, payload)


@router.get("/admin/lookups/{table}", response_model=list[admin_models.LookupOut])
def admin_list_lookups(table: str, u: CurrentUser = Depends(requires("admin"))):
    return admin_service.list_lookups(table)


@router.post("/admin/lookups/{table}", status_code=201, response_model=admin_models.LookupOut)
def admin_add_lookup(table: str, payload: admin_models.LookupCreate,
                     u: CurrentUser = Depends(requires("admin"))):
    return admin_service.add_lookup(table, payload)


@router.patch("/admin/lookups/{table}/{lookup_id}", response_model=admin_models.LookupOut)
def admin_update_lookup(table: str, lookup_id: int, payload: admin_models.LookupUpdate,
                        u: CurrentUser = Depends(requires("admin"))):
    return admin_service.update_lookup(table, lookup_id, payload)


# --- Profiles ------------------------------------------------------------------
@router.get("/admin/capabilities", response_model=list[admin_models.CapabilityEntry])
def admin_list_capabilities(u: CurrentUser = Depends(requires("admin"))):
    return admin_service.list_capabilities()


@router.get("/admin/profiles", response_model=list[admin_models.ProfileOut])
def admin_list_profiles(u: CurrentUser = Depends(requires("admin"))):
    return admin_service.list_profiles()


@router.post("/admin/profiles", status_code=201, response_model=admin_models.ProfileOut)
def admin_create_profile(payload: admin_models.ProfileCreate,
                         u: CurrentUser = Depends(requires("admin"))):
    return admin_service.create_profile(payload)


@router.patch("/admin/profiles/{profile_id}", response_model=admin_models.ProfileOut)
def admin_update_profile(profile_id: int, payload: admin_models.ProfileUpdate,
                         u: CurrentUser = Depends(requires("admin"))):
    return admin_service.update_profile(profile_id, payload)


@router.delete("/admin/profiles/{profile_id}", status_code=204)
def admin_delete_profile(profile_id: int, u: CurrentUser = Depends(requires("admin"))):
    admin_service.delete_profile(profile_id)


@router.get("/admin/profiles/{profile_id}/capabilities", response_model=admin_models.ProfileCapabilitiesUpdate)
def admin_get_profile_capabilities(profile_id: int, u: CurrentUser = Depends(requires("admin"))):
    return admin_service.get_profile_capabilities(profile_id)


@router.put("/admin/profiles/{profile_id}/capabilities", response_model=admin_models.ProfileCapabilitiesUpdate)
def admin_save_profile_capabilities(profile_id: int, payload: admin_models.ProfileCapabilitiesUpdate,
                                    u: CurrentUser = Depends(requires("admin"))):
    return admin_service.save_profile_capabilities(u, profile_id, payload)
