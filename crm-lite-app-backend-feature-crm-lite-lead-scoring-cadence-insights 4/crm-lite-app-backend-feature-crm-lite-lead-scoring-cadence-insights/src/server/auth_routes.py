"""Auth & RBAC module routes (§1/§3 of the API spec).

IMPLEMENTED — see services/auth_service.py. POST /auth/login is the real
authentication boundary now that there's no gateway fronting Entra SSO
(GET /auth/callback is dormant legacy scaffold, kept for if SSO is wired up
again later — see config.py's GATEWAY_CALLBACK_SECRET comment).
"""
from fastapi import APIRouter, Depends, Query, status

from src.models import auth_models
from src.services import auth_service
from src.services.email_client import get_optional_email_sender
from src.utils.security import CurrentUser, get_identity, require_gateway_callback

router = APIRouter(tags=["Auth"])


@router.post("/auth/login", response_model=auth_models.LoginOut)
def auth_login(payload: auth_models.LoginRequest):
    return auth_service.login(payload)


@router.post("/auth/setup-admin", response_model=auth_models.SetupAdminOut)
def auth_setup_admin(payload: auth_models.SetupAdminRequest,
                     email_sender=Depends(get_optional_email_sender)):
    # No auth dependency at all, deliberately — this exists specifically for
    # when no employee (and so no bearer token) can exist yet. Safe only
    # because auth_service.setup_admin() itself refuses outright the moment
    # any employee already exists, in every environment, permanently.
    return auth_service.setup_admin(payload, email_sender)


@router.post("/auth/change-password", status_code=status.HTTP_204_NO_CONTENT)
def auth_change_password(payload: auth_models.ChangePasswordRequest,
                         u: CurrentUser = Depends(get_identity)):
    # get_identity, not get_current_user: changing your own password is an
    # identity action, not an RBAC-gated business capability — a brand-new
    # hire with a temp password and no role assigned yet must still be able
    # to set their own password (same reasoning as PATCH /current-employee).
    auth_service.change_password(u, payload)


@router.get("/auth/callback", response_model=auth_models.CurrentEmployeeOut)
def auth_callback(
    entra_object_id: str = Query(..., description="Forwarded by the gateway after Entra SSO"),
    email: str = Query(...),
    full_name: str = Query(""),
    _gateway: None = Depends(require_gateway_callback),
):
    return auth_service.handle_sso_callback(entra_object_id, email, full_name)


@router.post("/auth/logout")
def auth_logout():
    return auth_service.logout()


@router.get("/current-employee", response_model=auth_models.CurrentEmployeeOut)
def current_employee(u: CurrentUser = Depends(get_identity)):
    return auth_service.get_current_employee(u)


@router.patch("/current-employee", response_model=auth_models.CurrentEmployeeOut)
def update_current_employee(payload: auth_models.CurrentEmployeeUpdate,
                            u: CurrentUser = Depends(get_identity)):
    return auth_service.update_current_employee(u, payload)
