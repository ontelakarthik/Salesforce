"""Models for the Platform module (§1/§12 of the API spec) — dashboard,
search, lookup reads, document upload URLs. IMPLEMENTED — see
services/platform_service.py and server/platform_routes.py.

Platform owns no dedicated ORM tables of its own: dashboard/SLA/expiry
computation are derived on read from CRM/Delivery/Contracts/Project tables,
never stored; search and `GET /lookups/{table}` are cross-cutting reads over
other modules' tables (lookup value *management*, i.e. writes, is Admin's —
see admin_models.py). This file holds the request/response schemas the
dashboard/search/lookup/document-upload-url endpoints need.
"""
import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class RepActivitySummary(BaseModel):
    """One row of the manager dashboard's per-rep breakdown — `None` for
    owner_employee_id is the team_totals row."""
    owner_employee_id: uuid.UUID | None = None
    leads_created: int
    leads_qualified: int
    leads_converted: int
    emails_sent: int
    calls_made: int
    # Distinct-lead counts (not activity counts) — a lead with 3 emails sent
    # still counts once. leads_contacted = >=1 EMAIL/CALL communication of
    # either direction; leads_responded = >=1 INBOUND communication or one
    # marked replied_at (same "has the lead replied" definition
    # crm_service._lead_has_replied_since() already uses for the cadence
    # scheduler) — see platform_service.manager_dashboard().
    leads_contacted: int = 0
    leads_responded: int = 0


class ManagerDashboardOut(BaseModel):
    """BDE-team activity/pipeline dashboard for a Sales Lead/Manager — see
    platform_service.manager_dashboard(). Distinct from DashboardOut below,
    which is the CLM app's own contracts/delivery dashboard."""
    date_from: date | None = None
    date_to: date | None = None
    team_totals: RepActivitySummary
    per_rep: list[RepActivitySummary]
    leaderboard: list[RepActivitySummary] = Field(
        description="per_rep sorted by (emails_sent + calls_made + leads_created), descending")
    total_leads: int
    leads_by_status: dict[str, int]
    conversion_rate_percent: float | None = None
    hot_lead_count: int


class DashboardOut(BaseModel):
    total_accounts: int
    total_agreements: int
    agreements_by_status: dict[str, int]
    overdue_agreements: int
    total_projects: int
    projects_by_status: dict[str, int]
    pending_timesheets: int
    unacknowledged_notifications: int


class SearchResultItem(BaseModel):
    entity_type: str = Field(description="account | agreement | project | opportunity")
    id: str
    label: str


class SearchOut(BaseModel):
    query: str
    results: list[SearchResultItem]


class UploadUrlCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str | None = Field(default=None, max_length=120)


class UploadUrlOut(BaseModel):
    sharepoint_item_id: uuid.UUID
    upload_url: str
    expires_at: datetime
