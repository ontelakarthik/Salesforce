"""Liveness / readiness probes (used by Azure Container Apps health checks)."""
from fastapi import APIRouter

from src.config.config_reader import settings

router = APIRouter(tags=["meta"])


@router.get("/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME, "env": settings.APP_ENV}


@router.get("/health/ready")
def ready():
    # TODO(CLM-PLATFORM, @platform-team): check DB connectivity before
    #       reporting ready.
    return {"status": "ready"}
