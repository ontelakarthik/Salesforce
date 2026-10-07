"""Platform module business logic (§1/§5/§12 of the API spec) — dashboard,
search, lookup reads, document upload URLs. IMPLEMENTED.

Rules enforced:
- dashboard/search : scoped by role like any list endpoint — SALES sees only
                     accounts they own (plus agreements/projects/opportunities
                     under those accounts); AE/LEADERSHIP/ADMIN see everything.
- overdue agreements: sla_due_at has passed and the agreement hasn't reached
                     SIGNED/EXPIRED/SUPERSEDED (computed on read, never stored).
- lookups          : read-only pass-through to admin_service's lookup
                     registry — value *management* (writes) stays Admin's.
- upload-url       : no real SharePoint integration exists yet, so this
                     synthesizes a placeholder response (a fresh item id +
                     a same-shaped URL) good enough for callers to exercise
                     the contract end-to-end; swap for a real Graph API call
                     when SharePoint wiring lands.

Employee/team provisioning is Admin's (admin_service.py); auth/session is
Auth's (auth_service.py) — this module composes over other modules'
repositories, it doesn't own any tables of its own.
"""
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from src.models import platform_models
from src.models.enums import AgreementStatus, CadenceTaskStatus, LeadStatus, TimesheetStatus
from src.repositories.activity_repository import CommunicationRepository, NotificationRepository
from src.repositories.contracts_repository import AgreementRepository, get_agreement_status_repository
from src.repositories.crm_repository import (
    AccountRepository, CadenceTaskRepository, LeadCadenceEnrollmentRepository, LeadRepository,
    OpportunityRepository,
)
from src.repositories.delivery_repository import SowTimesheetRepository
from src.repositories.project_repository import ProjectRepository, get_project_status_repository
from src.services import admin_service
from src.utils.error_handling import handle_errors
from src.utils.security import CurrentUser

_SLA_EXEMPT_STATUSES = {AgreementStatus.SIGNED.value, AgreementStatus.EXPIRED.value,
                        AgreementStatus.SUPERSEDED.value}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _owned_account_ids(user: CurrentUser, account_repo: AccountRepository) -> set[str] | None:
    """None means "no restriction" (any profile holding records.see_all sees
    everything); otherwise the set of account ids a SALES user is scoped to
    — their own plus any owned by a Role-Hierarchy subordinate (see
    CurrentUser.subordinate_employee_ids())."""
    if user.has_capability("records.see_all"):
        return None
    owner = user.employee_uuid()
    owner_ids = ({owner} if owner is not None else set()) | user.subordinate_employee_ids()
    if not owner_ids:
        return set()
    return {c.id for c in account_repo.list_for_owners(owner_ids)}


@handle_errors("load the dashboard")
def dashboard(user: CurrentUser, account_repo: AccountRepository, agreement_repo: AgreementRepository,
             project_repo: ProjectRepository, timesheet_repo: SowTimesheetRepository,
             notification_repo: NotificationRepository) -> platform_models.DashboardOut:
    owned = _owned_account_ids(user, account_repo)
    accounts = account_repo.list() if owned is None else [c for c in account_repo.list() if c.id in owned]
    agreements = [a for a in agreement_repo.list() if owned is None or a.account_id in owned]
    projects = [p for p in project_repo.list() if owned is None or p.account_id in owned]

    astatus_map = {s.id: s.code for s in get_agreement_status_repository().list()}
    agreements_by_status: dict[str, int] = {}
    overdue = 0
    now = _now()
    for a in agreements:
        code = astatus_map[a.agreement_status_id]
        agreements_by_status[code] = agreements_by_status.get(code, 0) + 1
        if a.sla_due_at and a.sla_due_at < now and code not in _SLA_EXEMPT_STATUSES:
            overdue += 1

    pstatus_map = {s.id: s.code for s in get_project_status_repository().list()}
    projects_by_status: dict[str, int] = {}
    for p in projects:
        code = pstatus_map[p.project_status_id]
        projects_by_status[code] = projects_by_status.get(code, 0) + 1

    if owned is None:
        pending_timesheets = len(
            [t for t in timesheet_repo.list() if t.status == TimesheetStatus.SUBMITTED.value])
    else:
        agreement_ids = {a.id for a in agreements}
        pending_timesheets = len([
            t for t in timesheet_repo.list()
            if t.status == TimesheetStatus.SUBMITTED.value and t.agreement_id in agreement_ids
        ])

    return platform_models.DashboardOut(
        total_accounts=len(accounts), total_agreements=len(agreements),
        agreements_by_status=agreements_by_status, overdue_agreements=overdue,
        total_projects=len(projects), projects_by_status=projects_by_status,
        pending_timesheets=pending_timesheets,
        unacknowledged_notifications=len(notification_repo.list_unacknowledged()),
    )


def _within_range(when: datetime, date_from: date | None, date_to: date | None) -> bool:
    if date_from and when.date() < date_from:
        return False
    if date_to and when.date() > date_to:
        return False
    return True


def _zero_summary() -> dict:
    return {"leads_created": 0, "leads_qualified": 0, "leads_converted": 0, "emails_sent": 0, "calls_made": 0}


#: Channels that count as "the lead has been contacted" (BRD Phase 3 #10) —
#: any EMAIL or CALL communication, either direction (an inbound cold email
#: that became a lead already counts, same as a rep-initiated outbound one).
_CONTACT_CHANNELS = {"EMAIL", "CALL"}


def _lead_has_responded(c) -> bool:
    """"Responded" (BRD Phase 3 #11) — an inbound communication, or an
    outbound one a rep has since marked replied via
    activity_service.mark_communication_replied(). Same definition
    crm_service._lead_has_replied_since() already uses for the cadence
    scheduler's FOLLOW_UP auto-skip logic."""
    return c.direction == "INBOUND" or c.replied_at is not None


@handle_errors("load the manager dashboard")
def manager_dashboard(
    user: CurrentUser, lead_repo: LeadRepository, comm_repo: CommunicationRepository, *,
    campaign_id=None, industry: str | None = None, owner_employee_id=None,
    date_from: date | None = None, date_to: date | None = None,
    hot_lead_score_threshold: int = 50,
) -> platform_models.ManagerDashboardOut:
    """A Sales Lead/Manager's team-activity + pipeline dashboard (BRD §5.11
    MV-1..MV-4) — distinct from the CLM app's own `dashboard()` above.
    Unlike every other list endpoint, this is intentionally NOT scoped to
    "rows I own" — a manager needs every rep's numbers, which is why it's
    gated behind its own capability (manager_dashboard.read, {AE,L,A}) rather
    than platform.read. Filters (campaign/industry/owner/date range) are the
    same axes a client would drill down into GET /leads with (MV-3)."""
    leads = list(lead_repo.list())
    if campaign_id is not None:
        leads = [lead for lead in leads if lead.campaign_id == campaign_id]
    if industry is not None:
        leads = [lead for lead in leads if (lead.industry or "").lower() == industry.lower()]
    if owner_employee_id is not None:
        leads = [lead for lead in leads if lead.owner_employee_id == owner_employee_id]
    if date_from or date_to:
        leads = [lead for lead in leads if _within_range(lead.created_at, date_from, date_to)]

    lead_ids = {lead.id for lead in leads}
    owner_by_lead = {lead.id: lead.owner_employee_id for lead in leads}

    comms = [c for c in comm_repo.list() if c.lead_id in lead_ids]
    if date_from or date_to:
        comms = [c for c in comms if _within_range(c.occurred_at, date_from, date_to)]

    reps: dict = {}

    def rep(owner) -> dict:
        return reps.setdefault(owner, _zero_summary())

    for lead in leads:
        r = rep(lead.owner_employee_id)
        r["leads_created"] += 1
        if lead.status == LeadStatus.QUALIFIED.value:
            r["leads_qualified"] += 1
        elif lead.status == LeadStatus.CONVERTED.value:
            r["leads_converted"] += 1

    # Distinct-lead sets, not per-communication counts — a lead with 3
    # outbound emails is still one "contacted" lead (BRD Phase 3 #12).
    contacted_by_owner: dict = {}
    responded_by_owner: dict = {}
    for c in comms:
        owner = owner_by_lead.get(c.lead_id)
        r = rep(owner)
        if c.channel == "EMAIL" and c.direction == "OUTBOUND":
            r["emails_sent"] += 1
        elif c.channel == "CALL":
            r["calls_made"] += 1
        if c.channel in _CONTACT_CHANNELS:
            contacted_by_owner.setdefault(owner, set()).add(c.lead_id)
        if _lead_has_responded(c):
            responded_by_owner.setdefault(owner, set()).add(c.lead_id)

    per_rep = [platform_models.RepActivitySummary(
        owner_employee_id=owner, **totals,
        leads_contacted=len(contacted_by_owner.get(owner, set())),
        leads_responded=len(responded_by_owner.get(owner, set())),
    ) for owner, totals in reps.items()]
    leaderboard = sorted(
        per_rep, key=lambda r: r.emails_sent + r.calls_made + r.leads_created, reverse=True)

    team_totals = platform_models.RepActivitySummary(
        owner_employee_id=None,
        leads_created=sum(r.leads_created for r in per_rep),
        leads_qualified=sum(r.leads_qualified for r in per_rep),
        leads_converted=sum(r.leads_converted for r in per_rep),
        emails_sent=sum(r.emails_sent for r in per_rep),
        calls_made=sum(r.calls_made for r in per_rep),
        leads_contacted=len({c.lead_id for c in comms if c.channel in _CONTACT_CHANNELS}),
        leads_responded=len({c.lead_id for c in comms if _lead_has_responded(c)}),
    )

    leads_by_status: dict[str, int] = {}
    for lead in leads:
        leads_by_status[lead.status] = leads_by_status.get(lead.status, 0) + 1
    total_leads = len(leads)
    converted = leads_by_status.get(LeadStatus.CONVERTED.value, 0)
    hot_lead_count = sum(1 for lead in leads if lead.lead_score >= hot_lead_score_threshold)

    return platform_models.ManagerDashboardOut(
        date_from=date_from, date_to=date_to, team_totals=team_totals, per_rep=per_rep,
        leaderboard=leaderboard, total_leads=total_leads, leads_by_status=leads_by_status,
        conversion_rate_percent=round(converted / total_leads * 100, 1) if total_leads else None,
        hot_lead_count=hot_lead_count,
    )


COMPLETED = "completed"
PENDING = "pending"
OVERDUE = "overdue"


def classify_cadence_task(status: str, due_date: date, today: date) -> str:
    """The Task Dashboard's one rule — every task is exactly one of:
    - DONE                              -> completed (never overdue, however old)
    - anything else, due_date < today   -> overdue
    - anything else, due today or later -> pending
    "Anything else" is PENDING *and* SKIPPED: a skipped task isn't completed,
    so it still counts as pending until its due date passes, then overdue. A
    reopened task is simply PENDING again, so it needs no special case."""
    if status == CadenceTaskStatus.DONE.value:
        return COMPLETED
    return OVERDUE if due_date < today else PENDING


@handle_errors("load the task dashboard")
def task_dashboard(
    user: CurrentUser, lead_repo: LeadRepository, enrollment_repo: LeadCadenceEnrollmentRepository,
    task_repo: CadenceTaskRepository, *, today: date | None = None,
) -> platform_models.TaskDashboardOut:
    """Cadence tasks per assigned rep, for the manager dashboard's "Task
    Dashboard" card. A cadence task has no owner column of its own: it
    belongs to an enrollment, which belongs to a lead, and the lead's
    owner_employee_id is the rep working it (same relationship
    crm_service.list_my_cadence_tasks() uses) — so a lead with no owner puts
    its tasks under Unassigned (owner_employee_id None). Like
    manager_dashboard() it is intentionally not scoped to "rows I own" (gated
    by manager_dashboard.read instead). Every task whose lead still exists is
    counted exactly once, whatever its status or enrollment state. `today` is
    UTC, the same clock the cadence scheduler uses for "due"."""
    today = today or _now().date()
    owner_by_lead = {lead.id: lead.owner_employee_id for lead in lead_repo.list()}
    lead_by_enrollment = {e.id: e.lead_id for e in enrollment_repo.list()}

    reps: dict = {}
    for task in task_repo.list():
        lead_id = lead_by_enrollment.get(task.enrollment_id)
        if lead_id not in owner_by_lead:
            continue  # its enrollment/lead no longer exists — nobody to attribute it to
        row = reps.setdefault(owner_by_lead[lead_id], {COMPLETED: 0, PENDING: 0, OVERDUE: 0})
        row[classify_cadence_task(task.status, task.due_date, today)] += 1

    def summary(owner, counts) -> platform_models.RepTaskSummary:
        return platform_models.RepTaskSummary(
            owner_employee_id=owner, assigned=sum(counts.values()),
            completed=counts[COMPLETED], pending=counts[PENDING], overdue=counts[OVERDUE])

    per_rep = sorted(
        (summary(owner, counts) for owner, counts in reps.items()),
        # busiest first, with the Unassigned bucket always last
        key=lambda r: (r.owner_employee_id is None, -r.assigned, str(r.owner_employee_id)))
    totals = {k: sum(r[k] for r in reps.values()) for k in (COMPLETED, PENDING, OVERDUE)}
    return platform_models.TaskDashboardOut(per_rep=per_rep, team_totals=summary(None, totals))


@handle_errors("run the search")
def search(user: CurrentUser, q: str, account_repo: AccountRepository,
          agreement_repo: AgreementRepository, project_repo: ProjectRepository,
          opportunity_repo: OpportunityRepository) -> platform_models.SearchOut:
    needle = q.strip().lower()
    owned = _owned_account_ids(user, account_repo)
    results: list[platform_models.SearchResultItem] = []
    if not needle:
        return platform_models.SearchOut(query=q, results=results)

    for c in account_repo.list():
        if (owned is None or c.id in owned) and needle in c.legal_name.lower():
            results.append(platform_models.SearchResultItem(
                entity_type="account", id=c.id, label=c.legal_name))

    for a in agreement_repo.list():
        if (owned is None or a.account_id in owned) and needle in a.title.lower():
            results.append(platform_models.SearchResultItem(
                entity_type="agreement", id=a.id, label=a.title))

    for p in project_repo.list():
        if (owned is None or p.account_id in owned) and needle in p.name.lower():
            results.append(platform_models.SearchResultItem(
                entity_type="project", id=p.id, label=p.name))

    for o in opportunity_repo.list():
        if (owned is None or o.account_id in owned) and needle in o.name.lower():
            results.append(platform_models.SearchResultItem(
                entity_type="opportunity", id=o.id, label=o.name))

    return platform_models.SearchOut(query=q, results=results)


# --- Lookups (read-only pass-through to admin's registry) -----------------------
@handle_errors("get lookups")
def get_lookups(table: str) -> list:
    return admin_service.list_lookups(table)


# --- Document upload URL (placeholder pending real SharePoint integration) -----
@handle_errors("create an upload URL")
def create_upload_url(payload: platform_models.UploadUrlCreate) -> platform_models.UploadUrlOut:
    item_id = uuid4()
    return platform_models.UploadUrlOut(
        sharepoint_item_id=item_id,
        upload_url=f"https://placeholder.sharepoint.local/upload/{item_id}/{payload.filename}",
        expires_at=_now() + timedelta(minutes=15),
    )
