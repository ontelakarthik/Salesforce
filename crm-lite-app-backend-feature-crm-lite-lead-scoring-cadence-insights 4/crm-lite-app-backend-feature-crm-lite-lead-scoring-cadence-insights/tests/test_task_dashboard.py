"""Task Dashboard — per-rep cadence-task counts (platform_service.task_dashboard()
/ GET /task-dashboard). Separate from the Rep leaderboard (manager-dashboard),
which these tests also check is untouched.

Two layers: the counting rules are exercised directly against in-memory
stand-ins for the three repositories with a fixed `today` (deterministic, no
DB), then a few end-to-end tests go through the real API and cadence engine."""
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.repositories.crm_repository import get_cadence_task_repository
from src.services import platform_service
from tests.test_cadence import TWO_STEPS, _deactivate_all_templates, _lead, _template

TODAY = date(2026, 10, 7)
FUTURE = TODAY + timedelta(days=3)
PAST = TODAY - timedelta(days=3)


class _Repo:
    def __init__(self, rows):
        self._rows = rows

    def list(self):
        return self._rows


class _World:
    """Builds leads/enrollments/tasks the way the real data hangs together:
    task -> enrollment -> lead -> owner."""

    def __init__(self):
        self.leads, self.enrollments, self.tasks = [], [], []

    def lead(self, owner):
        lead = SimpleNamespace(id=uuid.uuid4(), owner_employee_id=owner)
        enrollment = SimpleNamespace(id=uuid.uuid4(), lead_id=lead.id)
        self.leads.append(lead)
        self.enrollments.append(enrollment)
        return enrollment

    def task(self, enrollment, status, due):
        self.tasks.append(SimpleNamespace(
            id=uuid.uuid4(), enrollment_id=enrollment.id, cadence_step_id=uuid.uuid4(),
            status=status, due_date=due))

    def tasks_for(self, owner, *specs):
        """specs: (count, status, due) triples, all tasks of one rep."""
        enrollment = self.lead(owner)
        for count, status, due in specs:
            for _ in range(count):
                self.task(enrollment, status, due)

    def run(self):
        return platform_service.task_dashboard(
            None, _Repo(self.leads), _Repo(self.enrollments), _Repo(self.tasks), today=TODAY)


def _row(result, owner):
    return next(r for r in result.per_rep if r.owner_employee_id == owner)


def _counts(row):
    return (row.assigned, row.completed, row.pending, row.overdue)


REP = uuid.uuid4()


class TestClassification:
    def test_completed_is_never_pending_or_overdue_however_old(self):
        assert platform_service.classify_cadence_task("DONE", PAST, TODAY) == "completed"
        assert platform_service.classify_cadence_task("DONE", FUTURE, TODAY) == "completed"

    @pytest.mark.parametrize("status", ["PENDING", "SKIPPED"])
    def test_future_or_today_is_pending_and_past_is_overdue(self, status):
        assert platform_service.classify_cadence_task(status, FUTURE, TODAY) == "pending"
        assert platform_service.classify_cadence_task(status, TODAY, TODAY) == "pending"  # due today isn't late yet
        assert platform_service.classify_cadence_task(status, TODAY - timedelta(days=1), TODAY) == "overdue"


class TestSpecScenarios:
    """The five scenarios from the requirement, 10 tasks each."""

    def test_1_all_completed(self):
        w = _World()
        w.tasks_for(REP, (10, "DONE", PAST))
        assert _counts(_row(w.run(), REP)) == (10, 10, 0, 0)

    def test_2_completed_and_active_future(self):
        w = _World()
        w.tasks_for(REP, (5, "DONE", PAST), (5, "PENDING", FUTURE))
        assert _counts(_row(w.run(), REP)) == (10, 5, 5, 0)

    def test_3_completed_active_future_and_active_past(self):
        w = _World()
        w.tasks_for(REP, (5, "DONE", PAST), (3, "PENDING", FUTURE), (2, "PENDING", PAST))
        assert _counts(_row(w.run(), REP)) == (10, 5, 3, 2)

    def test_4_skipped_with_a_future_due_date_is_pending(self):
        w = _World()
        w.tasks_for(REP, (5, "DONE", PAST), (3, "PENDING", FUTURE), (2, "SKIPPED", FUTURE))
        assert _counts(_row(w.run(), REP)) == (10, 5, 5, 0)

    def test_5_skipped_with_a_past_due_date_is_overdue(self):
        w = _World()
        w.tasks_for(REP, (5, "DONE", PAST), (3, "PENDING", FUTURE), (2, "SKIPPED", PAST))
        assert _counts(_row(w.run(), REP)) == (10, 5, 3, 2)

    def test_a_skipped_task_is_never_counted_as_completed(self):
        w = _World()
        w.tasks_for(REP, (4, "SKIPPED", FUTURE), (4, "SKIPPED", PAST))
        assert _counts(_row(w.run(), REP)) == (8, 0, 4, 4)


class TestAggregation:
    def test_every_task_is_counted_once_and_assigned_equals_the_three_buckets(self):
        w = _World()
        reps = [uuid.uuid4() for _ in range(4)] + [None]
        statuses = ["DONE", "PENDING", "SKIPPED"]
        dues = [PAST, TODAY, FUTURE]
        total = 0
        for i, owner in enumerate(reps):
            for j, status in enumerate(statuses):
                for k, due in enumerate(dues):
                    n = i + j + k + 1
                    w.tasks_for(owner, (n, status, due))
                    total += n
        result = w.run()

        for row in result.per_rep:
            assert row.assigned == row.completed + row.pending + row.overdue
        assert sum(r.assigned for r in result.per_rep) == total == len(w.tasks)
        assert result.team_totals.assigned == total
        assert result.team_totals.assigned == (
            result.team_totals.completed + result.team_totals.pending + result.team_totals.overdue)

    def test_all_of_a_reps_leads_and_cadences_roll_up_into_one_row(self):
        w = _World()
        w.tasks_for(REP, (2, "DONE", PAST))
        w.tasks_for(REP, (1, "PENDING", FUTURE))  # a second lead owned by the same rep
        result = w.run()
        assert len(result.per_rep) == 1
        assert _counts(result.per_rep[0]) == (3, 2, 1, 0)

    def test_tasks_of_an_ownerless_lead_go_under_unassigned_and_sort_last(self):
        w = _World()
        w.tasks_for(None, (9, "PENDING", FUTURE))
        w.tasks_for(REP, (1, "PENDING", FUTURE))
        result = w.run()
        assert [r.owner_employee_id for r in result.per_rep] == [REP, None]
        assert _counts(result.per_rep[1]) == (9, 0, 9, 0)

    def test_reps_are_ordered_busiest_first(self):
        w = _World()
        small, big = uuid.uuid4(), uuid.uuid4()
        w.tasks_for(small, (2, "PENDING", FUTURE))
        w.tasks_for(big, (5, "PENDING", FUTURE))
        assert [r.owner_employee_id for r in w.run().per_rep] == [big, small]

    def test_a_task_whose_lead_is_gone_is_not_attributed_to_anyone(self):
        w = _World()
        w.tasks_for(REP, (2, "PENDING", FUTURE))
        w.leads.clear()  # e.g. the lead was deleted
        result = w.run()
        assert result.per_rep == []
        assert result.team_totals.assigned == 0

    def test_no_tasks_gives_an_empty_dashboard(self):
        result = _World().run()
        assert result.per_rep == []
        assert _counts(result.team_totals) == (0, 0, 0, 0)

    def test_a_reopened_task_is_classified_by_its_current_state(self):
        # Reopen turns SKIPPED back into PENDING — same row, same due date.
        w = _World()
        w.tasks_for(REP, (1, "PENDING", FUTURE), (1, "PENDING", PAST))  # two reopened tasks
        assert _counts(_row(w.run(), REP)) == (2, 0, 1, 1)


# --- through the real API + cadence engine ----------------------------------------


@pytest.fixture(autouse=True)
def _no_active_template_left_behind(client, admin_headers):
    _deactivate_all_templates(client, admin_headers)
    yield
    _deactivate_all_templates(client, admin_headers)


def _rep(client, headers):
    r = client.post("/api/v1/admin/employees",
                    json={"email": f"rep.{uuid.uuid4()}@example.com", "full_name": "Task Rep"}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _dashboard_row(client, headers, owner):
    r = client.get("/api/v1/task-dashboard", headers=headers)
    assert r.status_code == 200, r.text
    return next((row for row in r.json()["per_rep"] if row["owner_employee_id"] == owner), None)


def _as_tuple(row):
    return (row["assigned"], row["completed"], row["pending"], row["overdue"])


class TestTaskDashboardApi:
    def test_a_rep_with_no_tasks_has_no_row(self, client, admin_headers):
        assert _dashboard_row(client, admin_headers, _rep(client, admin_headers)) is None

    def test_task_lifecycle_moves_between_pending_overdue_and_completed(self, client, admin_headers):
        rep = _rep(client, admin_headers)
        lead = _lead(client, admin_headers, owner_employee_id=rep)
        template = _template(client, admin_headers, TWO_STEPS)
        enrolled = client.post(f"/api/v1/leads/{lead['id']}/cadence/enroll",
                               json={"cadence_template_id": template["id"]}, headers=admin_headers).json()
        call_id = enrolled["tasks"][0]["id"]  # CALL, due today

        # one open task, due today -> Pending
        assert _as_tuple(_dashboard_row(client, admin_headers, rep)) == (1, 0, 1, 0)

        # skipping it creates the next step (EMAIL, due in 3 days). The skipped CALL is due today
        # (not yet past) -> still Pending, never Completed.
        client.post(f"/api/v1/cadence-tasks/{call_id}/complete",
                    json={"outcome_status": "SKIPPED"}, headers=admin_headers)
        assert _as_tuple(_dashboard_row(client, admin_headers, rep)) == (2, 0, 2, 0)

        # once the skipped task's due date has passed (the server's "today" is UTC) it becomes Overdue; the EMAIL is untouched
        get_cadence_task_repository().update(call_id, due_date=datetime.now(timezone.utc).date() - timedelta(days=1), updated_by=None)
        assert _as_tuple(_dashboard_row(client, admin_headers, rep)) == (2, 0, 1, 1)

        # reopening keeps the same task (no new one) and it is still past due -> still Overdue
        client.post(f"/api/v1/cadence-tasks/{call_id}/reopen", headers=admin_headers)
        assert _as_tuple(_dashboard_row(client, admin_headers, rep)) == (2, 0, 1, 1)

        # completing it moves it to Completed — a past due date no longer makes it Overdue
        client.post(f"/api/v1/cadence-tasks/{call_id}/complete",
                    json={"outcome_status": "DONE"}, headers=admin_headers)
        assert _as_tuple(_dashboard_row(client, admin_headers, rep)) == (2, 1, 1, 0)

    def test_rows_are_per_rep_and_never_mix_owners(self, client, admin_headers):
        rep_a, rep_b = _rep(client, admin_headers), _rep(client, admin_headers)
        template = _template(client, admin_headers, TWO_STEPS)
        for rep in (rep_a, rep_b):
            lead = _lead(client, admin_headers, owner_employee_id=rep)
            client.post(f"/api/v1/leads/{lead['id']}/cadence/enroll",
                        json={"cadence_template_id": template["id"]}, headers=admin_headers)
        assert _as_tuple(_dashboard_row(client, admin_headers, rep_a)) == (1, 0, 1, 0)
        assert _as_tuple(_dashboard_row(client, admin_headers, rep_b)) == (1, 0, 1, 0)

    def test_every_row_and_the_team_total_satisfy_assigned_equals_the_buckets(self, client, admin_headers):
        body = client.get("/api/v1/task-dashboard", headers=admin_headers).json()
        for row in [*body["per_rep"], body["team_totals"]]:
            assert row["assigned"] == row["completed"] + row["pending"] + row["overdue"]

    def test_requires_the_manager_dashboard_capability(self, client, sales_headers, leadership_headers):
        assert client.get("/api/v1/task-dashboard", headers=sales_headers).status_code == 403
        assert client.get("/api/v1/task-dashboard", headers=leadership_headers).status_code == 200

    def test_the_rep_leaderboard_payload_is_unchanged(self, client, admin_headers):
        body = client.get("/api/v1/manager-dashboard", headers=admin_headers).json()
        assert set(body) == {
            "date_from", "date_to", "team_totals", "per_rep", "leaderboard", "total_leads",
            "leads_by_status", "conversion_rate_percent", "hot_lead_count"}
        assert set(body["team_totals"]) == {
            "owner_employee_id", "leads_created", "leads_qualified", "leads_converted",
            "emails_sent", "calls_made", "leads_contacted", "leads_responded"}
