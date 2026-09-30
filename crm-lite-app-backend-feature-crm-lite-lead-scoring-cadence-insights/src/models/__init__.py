"""Import model modules here so Alembic autogenerate sees their tables.

One module per service (auth, crm, contracts, delivery, project, activity,
admin, platform — matching the API spec's §1 service-boundary table) — each
stays a no-op import until its tables are defined.
"""
from src.models.base import Base  # noqa: F401
from src.models import (  # noqa: E402,F401
    activity_models,
    admin_models,
    auth_models,
    contracts_models,
    crm_models,
    delivery_models,
    platform_models,
    project_models,
)
