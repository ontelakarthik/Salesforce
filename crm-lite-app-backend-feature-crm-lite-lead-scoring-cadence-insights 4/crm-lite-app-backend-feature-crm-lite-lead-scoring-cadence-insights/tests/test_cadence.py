"""Sales Cadence engine + rule-based Lead Scoring — see crm_service.py's
enroll_lead_in_cadence()/complete_cadence_task()/_compute_lead_score()."""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from src.config.config_reader import get_settings
from src.services.auth_service import mint_token_for_profiles

_SCHEDULER_SECRET = "test-only-cadence-scheduler-secret"


def setup_module():
    get_settings().CADENCE_SCHEDULER_SECRET = _SCHEDULER_SECRET


def teardown_module():
    get_settings().CADENCE_SCHEDULER_SECRET = None


def _deactivate_all_templates(client, headers):
    r = client.get("/api/v1/cadence-templates", headers=headers)
    if r.status_code == 200:
        for t in r.json():
            if t.get("is_active"):
                client.patch(f"/api/v1/cadence-templates/{t['id']}",
                            json={"is_active": False}, headers=headers)


@pytest.fixture(autouse=True)
def _isolate_cadence_template_activation(client, admin_headers):
    """This file exercises create_lead()'s new auto-enroll-into-the-Active-
    template behavior indirectly on every _lead() call (since a template
    created earlier in this same module, or a leftover from another test
    file, may still be Active) — most of the tests below are about manual
    enrollment via POST .../cadence/enroll and would otherwise get a
    surprise LEAD_ALREADY_IN_ACTIVE_CADENCE 409 the moment _lead() runs
    while some other template happens to be Active. Deactivating everything
    before AND after each test keeps every test in this module starting
    from (and leaving behind) a clean "no active cadence" slate, regardless
    of what ran before or will run after it in the same session."""
    _deactivate_all_templates(client, admin_headers)
    yield
    _deactivate_all_templates(client, admin_headers)


def _scheduler_headers():
    return {"X-Cadence-Scheduler-Secret": _SCHEDULER_SECRET}


def _lead(client, headers, **overrides):
    payload = {"company_name": "Meridian Health", "contact_email": "test.lead@example.com", "first_name": "Ananya", "last_name": "Rao"} | overrides
    r = client.post("/api/v1/leads", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _template(client, headers, steps):
    r = client.post("/api/v1/cadence-templates",
                    json={"name": "Outbound Playbook", "description": "Standard sequence"},
                    headers=headers)
    assert r.status_code == 201, r.text
    template = r.json()
    for step in steps:
        r = client.post(f"/api/v1/cadence-templates/{template['id']}/steps", json=step, headers=headers)
        assert r.status_code == 201, r.text
    r = client.get(f"/api/v1/cadence-templates/{template['id']}", headers=headers)
    return r.json()


def _log_inbound_reply(client, headers, lead_id, occurred_at=None):
    """Simulates the lead replying — an INBOUND Communication logged against
    them (e.g. what POST /email-intake/poll would create for a real reply).
    Used to exercise FOLLOW_UP's "has the lead replied" condition without
    depending on live email infrastructure."""
    r = client.post(f"/api/v1/leads/{lead_id}/communications", json={
        "direction": "INBOUND", "channel": "EMAIL", "subject": "Re: following up",
        "occurred_at": (occurred_at or datetime.now(timezone.utc)).isoformat(),
    }, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _add_business_days(start: date, n: int) -> date:
    """Reference oracle (independent of crm_service._compute_due_date) for
    the skip_weekends=True spec: walk forward one calendar day at a time,
    counting only Mon-Fri, until n business days have been counted."""
    current = start
    remaining = n
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


TWO_STEPS = [
    {"step_order": 1, "step_type": "CALL", "subject": "Intro call", "wait_days": 0},
    {"step_order": 2, "step_type": "EMAIL", "subject": "Follow-up email", "wait_days": 3},
]


class TestCadenceEnrollment:
    def test_enroll_requires_active_template(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        template = _template(client, admin_headers, TWO_STEPS)
        client.patch(f"/api/v1/cadence-templates/{template['id']}", json={"is_active": False},
                    headers=admin_headers)
        r = client.post(f"/api/v1/leads/{lead['id']}/cadence/enroll",
                        json={"cadence_template_id": template["id"]}, headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "CADENCE_TEMPLATE_INACTIVE"

    def test_enroll_requires_template_with_steps(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        template = _template(client, admin_headers, [])
        r = client.post(f"/api/v1/leads/{lead['id']}/cadence/enroll",
                        json={"cadence_template_id": template["id"]}, headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "CADENCE_TEMPLATE_HAS_NO_STEPS"

    def test_enroll_creates_first_task_only(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        template = _template(client, admin_headers, TWO_STEPS)
        r = client.post(f"/api/v1/leads/{lead['id']}/cadence/enroll",
                        json={"cadence_template_id": template["id"]}, headers=admin_headers)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["enrollment"]["status"] == "ACTIVE"
        assert body["enrollment"]["current_step_order"] == 1
        assert len(body["tasks"]) == 1
        assert body["tasks"][0]["status"] == "PENDING"
        assert body["tasks"][0]["step_type"] == "CALL"

    def test_enroll_blocks_second_active_enrollment(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        template = _template(client, admin_headers, TWO_STEPS)
        r = client.post(f"/api/v1/leads/{lead['id']}/cadence/enroll",
                        json={"cadence_template_id": template["id"]}, headers=admin_headers)
        assert r.status_code == 201

        r = client.post(f"/api/v1/leads/{lead['id']}/cadence/enroll",
                        json={"cadence_template_id": template["id"]}, headers=admin_headers)
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "LEAD_ALREADY_IN_ACTIVE_CADENCE"

    def test_enroll_lead_not_found(self, client, admin_headers):
        template = _template(client, admin_headers, TWO_STEPS)
        r = client.post(f"/api/v1/leads/{uuid.uuid4()}/cadence/enroll",
                        json={"cadence_template_id": template["id"]}, headers=admin_headers)
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "LEAD_NOT_FOUND"

    def test_enroll_template_not_found(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        r = client.post(f"/api/v1/leads/{lead['id']}/cadence/enroll",
                        json={"cadence_template_id": str(uuid.uuid4())}, headers=admin_headers)
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "CADENCE_TEMPLATE_NOT_FOUND"


class TestAutoEnrollmentOnLeadCreate:
    """create_lead() auto-enrolling a brand-new lead into whichever
    CadenceTemplate is currently Active (BRD Phase 2 #7) — no manual
    "Enroll in cadence" click needed. See crm_service._auto_enroll_new_lead()
    and _get_active_cadence_template()."""

    def test_new_lead_is_auto_enrolled_in_the_active_template(self, client, admin_headers):
        template = _template(client, admin_headers, TWO_STEPS)  # active by default
        lead = _lead(client, admin_headers)

        r = client.get(f"/api/v1/leads/{lead['id']}/cadence", headers=admin_headers)
        assert r.status_code == 200, r.text
        detail = r.json()
        assert detail["enrollment"]["cadence_template_id"] == template["id"]
        assert detail["enrollment"]["status"] == "ACTIVE"
        assert len(detail["tasks"]) == 1
        assert detail["tasks"][0]["step_type"] == "CALL"

    def test_new_lead_is_not_enrolled_when_no_template_is_active(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        r = client.get(f"/api/v1/leads/{lead['id']}/cadence", headers=admin_headers)
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "LEAD_HAS_NO_CADENCE_ENROLLMENT"

    def test_new_lead_is_not_enrolled_when_active_template_has_no_steps(self, client, admin_headers):
        _template(client, admin_headers, [])  # active, but zero steps
        lead = _lead(client, admin_headers)
        r = client.get(f"/api/v1/leads/{lead['id']}/cadence", headers=admin_headers)
        assert r.status_code == 404

    def test_only_one_template_stays_active_when_a_second_is_created(self, client, admin_headers):
        first = _template(client, admin_headers, TWO_STEPS)
        second = _template(client, admin_headers, TWO_STEPS)  # creating this deactivates `first`

        r = client.get(f"/api/v1/cadence-templates/{first['id']}", headers=admin_headers)
        assert r.json()["is_active"] is False
        r = client.get(f"/api/v1/cadence-templates/{second['id']}", headers=admin_headers)
        assert r.json()["is_active"] is True

        lead = _lead(client, admin_headers)
        detail = client.get(f"/api/v1/leads/{lead['id']}/cadence", headers=admin_headers).json()
        assert detail["enrollment"]["cadence_template_id"] == second["id"]

    def test_activating_a_template_via_patch_deactivates_the_previous_active_one(self, client, admin_headers):
        first = _template(client, admin_headers, TWO_STEPS)
        second = _template(client, admin_headers, TWO_STEPS)
        # Explicitly re-activate `first` — should deactivate `second`, not
        # merely leave both active.
        r = client.patch(f"/api/v1/cadence-templates/{first['id']}", json={"is_active": True},
                         headers=admin_headers)
        assert r.status_code == 200, r.text
        assert r.json()["is_active"] is True
        r = client.get(f"/api/v1/cadence-templates/{second['id']}", headers=admin_headers)
        assert r.json()["is_active"] is False


class TestCadenceCancellation:
    def test_cancel_ends_the_enrollment_and_skips_the_pending_task(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        template = _template(client, admin_headers, TWO_STEPS)
        client.post(f"/api/v1/leads/{lead['id']}/cadence/enroll",
                   json={"cadence_template_id": template["id"]}, headers=admin_headers)

        r = client.post(f"/api/v1/leads/{lead['id']}/cadence/cancel", headers=admin_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["enrollment"]["status"] == "CANCELLED"
        assert len(body["tasks"]) == 1
        assert body["tasks"][0]["status"] == "SKIPPED"

    def test_cancelled_enrollment_frees_the_lead_to_re_enroll(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        template = _template(client, admin_headers, TWO_STEPS)
        client.post(f"/api/v1/leads/{lead['id']}/cadence/enroll",
                   json={"cadence_template_id": template["id"]}, headers=admin_headers)
        client.post(f"/api/v1/leads/{lead['id']}/cadence/cancel", headers=admin_headers)

        r = client.post(f"/api/v1/leads/{lead['id']}/cadence/enroll",
                        json={"cadence_template_id": template["id"]}, headers=admin_headers)
        assert r.status_code == 201, r.text

    def test_cancel_with_no_active_enrollment_404s(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        r = client.post(f"/api/v1/leads/{lead['id']}/cadence/cancel", headers=admin_headers)
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "LEAD_HAS_NO_ACTIVE_CADENCE_ENROLLMENT"

    def test_sales_cannot_cancel_enrollment_on_unowned_lead(self, client, admin_headers, sales_headers):
        lead = _lead(client, admin_headers)  # owner_employee_id left unset
        template = _template(client, admin_headers, TWO_STEPS)
        client.post(f"/api/v1/leads/{lead['id']}/cadence/enroll",
                   json={"cadence_template_id": template["id"]}, headers=admin_headers)

        r = client.post(f"/api/v1/leads/{lead['id']}/cadence/cancel", headers=sales_headers)
        assert r.status_code == 403


class TestCadenceTaskCompletion:
    def _enroll(self, client, headers, steps=TWO_STEPS):
        lead = _lead(client, headers)
        template = _template(client, headers, steps)
        r = client.post(f"/api/v1/leads/{lead['id']}/cadence/enroll",
                        json={"cadence_template_id": template["id"]}, headers=headers)
        assert r.status_code == 201
        return lead, template, r.json()

    def test_complete_task_advances_to_next_step(self, client, admin_headers):
        lead, _template, enrolled = self._enroll(client, admin_headers)
        first_task_id = enrolled["tasks"][0]["id"]

        r = client.post(f"/api/v1/cadence-tasks/{first_task_id}/complete",
                        json={"outcome_status": "DONE"}, headers=admin_headers)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "DONE"

        r = client.get(f"/api/v1/leads/{lead['id']}/cadence", headers=admin_headers)
        body = r.json()
        assert body["enrollment"]["current_step_order"] == 2
        assert body["enrollment"]["status"] == "ACTIVE"
        assert len(body["tasks"]) == 2
        new_task = next(t for t in body["tasks"] if t["id"] != first_task_id)
        assert new_task["status"] == "PENDING"
        assert new_task["step_type"] == "EMAIL"

    def test_skipped_advances_same_as_done(self, client, admin_headers):
        lead, _template, enrolled = self._enroll(client, admin_headers)
        first_task_id = enrolled["tasks"][0]["id"]

        r = client.post(f"/api/v1/cadence-tasks/{first_task_id}/complete",
                        json={"outcome_status": "SKIPPED"}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["status"] == "SKIPPED"

        r = client.get(f"/api/v1/leads/{lead['id']}/cadence", headers=admin_headers)
        body = r.json()
        assert body["enrollment"]["current_step_order"] == 2
        assert len(body["tasks"]) == 2

    def test_completing_last_step_marks_enrollment_completed(self, client, admin_headers):
        lead, _template, enrolled = self._enroll(client, admin_headers)
        first_task_id = enrolled["tasks"][0]["id"]

        client.post(f"/api/v1/cadence-tasks/{first_task_id}/complete",
                   json={"outcome_status": "DONE"}, headers=admin_headers)
        r = client.get(f"/api/v1/leads/{lead['id']}/cadence", headers=admin_headers)
        second_task = next(t for t in r.json()["tasks"] if t["id"] != first_task_id)

        r = client.post(f"/api/v1/cadence-tasks/{second_task['id']}/complete",
                        json={"outcome_status": "DONE"}, headers=admin_headers)
        assert r.status_code == 200

        r = client.get(f"/api/v1/leads/{lead['id']}/cadence", headers=admin_headers)
        body = r.json()
        assert body["enrollment"]["status"] == "COMPLETED"
        assert body["enrollment"]["completed_at"] is not None
        assert len(body["tasks"]) == 2  # no third task created

    def test_cannot_complete_already_completed_task(self, client, admin_headers):
        _lead_row, _template, enrolled = self._enroll(client, admin_headers)
        first_task_id = enrolled["tasks"][0]["id"]
        client.post(f"/api/v1/cadence-tasks/{first_task_id}/complete",
                   json={"outcome_status": "DONE"}, headers=admin_headers)

        r = client.post(f"/api/v1/cadence-tasks/{first_task_id}/complete",
                        json={"outcome_status": "DONE"}, headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "CADENCE_TASK_NOT_PENDING"

    def test_complete_task_not_found(self, client, admin_headers):
        r = client.post(f"/api/v1/cadence-tasks/{uuid.uuid4()}/complete",
                        json={"outcome_status": "DONE"}, headers=admin_headers)
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "CADENCE_TASK_NOT_FOUND"


class TestCadenceScope:
    def test_sales_cannot_complete_task_on_unowned_lead(self, client, admin_headers, sales_headers):
        owner = client.post("/api/v1/admin/employees",
                            json={"email": f"owner.{uuid.uuid4()}@example.com", "full_name": "Owner Rep"},
                            headers=admin_headers).json()
        lead = _lead(client, admin_headers, owner_employee_id=owner["id"])
        template = _template(client, admin_headers, TWO_STEPS)
        enrolled = client.post(f"/api/v1/leads/{lead['id']}/cadence/enroll",
                               json={"cadence_template_id": template["id"]}, headers=admin_headers).json()
        task_id = enrolled["tasks"][0]["id"]

        r = client.post(f"/api/v1/cadence-tasks/{task_id}/complete",
                        json={"outcome_status": "DONE"}, headers=sales_headers)
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "FORBIDDEN"

    def test_sales_can_complete_task_on_own_lead(self, client, admin_headers, sales_headers):
        owner = client.post("/api/v1/admin/employees",
                            json={"email": f"owner.{uuid.uuid4()}@example.com", "full_name": "Owner Rep"},
                            headers=admin_headers).json()
        own_headers = {"Authorization": f"Bearer {mint_token_for_profiles(owner['id'], {'SALES'})}"}
        lead = _lead(client, admin_headers, owner_employee_id=owner["id"])
        template = _template(client, admin_headers, TWO_STEPS)
        enrolled = client.post(f"/api/v1/leads/{lead['id']}/cadence/enroll",
                               json={"cadence_template_id": template["id"]}, headers=own_headers).json()
        task_id = enrolled["tasks"][0]["id"]

        r = client.post(f"/api/v1/cadence-tasks/{task_id}/complete",
                        json={"outcome_status": "DONE"}, headers=own_headers)
        assert r.status_code == 200


class TestLeadScoring:
    """This is a persistent, shared Postgres DB with no per-test rollback (see
    TestCampaigns' "any(...)" assertions elsewhere in this suite for the same
    convention) — every rule created here must use a value unique to this
    test invocation (a fresh uuid4 per call) so it can't be matched by a rule
    some other test (or a prior run) already left behind, and absolute score
    assertions stay exact rather than accidentally summing multiple rules."""

    def _rule(self, client, admin_headers, **overrides):
        payload = {"name": "Rule", "field_name": "industry", "operator": "EQUALS",
                  "comparison_value": str(uuid.uuid4()), "points": 20} | overrides
        r = client.post("/api/v1/lead-scoring-rules", json=payload, headers=admin_headers)
        assert r.status_code == 201, r.text
        return r.json()

    def test_score_recomputed_on_create(self, client, admin_headers):
        unique_industry = f"industry-{uuid.uuid4()}"
        self._rule(client, admin_headers, field_name="industry", operator="EQUALS",
                  comparison_value=unique_industry, points=20)

        matching = _lead(client, admin_headers, industry=unique_industry)
        assert matching["lead_score"] == 20

        non_matching = _lead(client, admin_headers, industry=f"other-{uuid.uuid4()}")
        assert non_matching["lead_score"] == 0

    def test_score_floors_at_zero(self, client, admin_headers):
        unique_industry = f"industry-{uuid.uuid4()}"
        self._rule(client, admin_headers, field_name="industry", operator="EQUALS",
                  comparison_value=unique_industry, points=5)
        self._rule(client, admin_headers, field_name="industry", operator="EQUALS",
                  comparison_value=unique_industry, points=-20)

        lead = _lead(client, admin_headers, industry=unique_industry)
        assert lead["lead_score"] == 0  # 5 - 20 = -15, floored to 0

    def test_score_recomputed_on_update(self, client, admin_headers):
        unique_industry = f"industry-{uuid.uuid4()}"
        self._rule(client, admin_headers, field_name="industry", operator="EQUALS",
                  comparison_value=unique_industry, points=20)
        lead = _lead(client, admin_headers, industry=f"other-{uuid.uuid4()}")
        assert lead["lead_score"] == 0

        r = client.patch(f"/api/v1/leads/{lead['id']}", json={"industry": unique_industry},
                         headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["lead_score"] == 20

    def test_inactive_rule_not_applied(self, client, admin_headers):
        unique_industry = f"industry-{uuid.uuid4()}"
        rule = self._rule(client, admin_headers, field_name="industry", operator="EQUALS",
                          comparison_value=unique_industry, points=20)
        client.patch(f"/api/v1/lead-scoring-rules/{rule['id']}", json={"is_active": False},
                    headers=admin_headers)
        lead = _lead(client, admin_headers, industry=unique_industry)
        assert lead["lead_score"] == 0

    def test_rule_change_does_not_retroactively_rescore_existing_leads(self, client, admin_headers):
        unique_industry = f"industry-{uuid.uuid4()}"
        lead = _lead(client, admin_headers, industry=unique_industry)
        assert lead["lead_score"] == 0

        self._rule(client, admin_headers, field_name="industry", operator="EQUALS",
                  comparison_value=unique_industry, points=20)

        r = client.get(f"/api/v1/leads/{lead['id']}", headers=admin_headers)
        assert r.json()["lead_score"] == 0  # unchanged until the lead is next updated

    def test_score_breakdown_lists_only_matching_active_rules(self, client, admin_headers):
        unique_industry = f"industry-{uuid.uuid4()}"
        matching = self._rule(client, admin_headers, name="Matches", field_name="industry",
                              operator="EQUALS", comparison_value=unique_industry, points=20)
        self._rule(client, admin_headers, name="Does not match", field_name="industry",
                  operator="EQUALS", comparison_value=f"other-{uuid.uuid4()}", points=15)
        inactive = self._rule(client, admin_headers, name="Inactive but would match",
                              field_name="industry", operator="EQUALS",
                              comparison_value=unique_industry, points=99)
        client.patch(f"/api/v1/lead-scoring-rules/{inactive['id']}", json={"is_active": False},
                    headers=admin_headers)

        lead = _lead(client, admin_headers, industry=unique_industry)
        r = client.get(f"/api/v1/leads/{lead['id']}/score-breakdown", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert [entry["rule_id"] for entry in body] == [matching["id"]]
        assert body[0]["name"] == "Matches"
        assert body[0]["points"] == 20

    def test_score_breakdown_scope_blocks_unowned_lead(self, client, admin_headers, sales_headers):
        lead = _lead(client, admin_headers)  # owner_employee_id left unset
        r = client.get(f"/api/v1/leads/{lead['id']}/score-breakdown", headers=sales_headers)
        assert r.status_code == 403


class TestMyCadenceTasks:
    """GET /cadence-tasks/my -- feeds the personal rep dashboard's cadence
    task list. Uses _owned_by() (literal ownership only, not Role Hierarchy
    subordinates) so a manager's "my tasks" never includes their reports'."""

    def test_returns_only_my_own_pending_tasks_with_lead_id(self, client, admin_headers):
        rep = client.post("/api/v1/admin/employees",
                          json={"email": f"mytasks.{uuid.uuid4().hex[:8]}@example.com",
                               "full_name": "My Tasks Rep"},
                          headers=admin_headers).json()
        rep_headers = {"Authorization": f"Bearer {mint_token_for_profiles(rep['id'], {'SALES'})}"}

        my_lead = _lead(client, admin_headers, owner_employee_id=rep["id"])
        other_lead = _lead(client, admin_headers)  # unowned -- not this rep's
        template = _template(client, admin_headers, TWO_STEPS)
        client.post(f"/api/v1/leads/{my_lead['id']}/cadence/enroll",
                   json={"cadence_template_id": template["id"]}, headers=admin_headers)
        client.post(f"/api/v1/leads/{other_lead['id']}/cadence/enroll",
                   json={"cadence_template_id": template["id"]}, headers=admin_headers)

        r = client.get("/api/v1/cadence-tasks/my", headers=rep_headers)
        assert r.status_code == 200
        tasks = r.json()
        assert len(tasks) == 1
        assert tasks[0]["lead_id"] == my_lead["id"]
        assert tasks[0]["status"] == "PENDING"

    def test_admin_with_no_owned_leads_sees_none(self, client, admin_headers):
        lead = _lead(client, admin_headers)  # owned by nobody real
        template = _template(client, admin_headers, TWO_STEPS)
        client.post(f"/api/v1/leads/{lead['id']}/cadence/enroll",
                   json={"cadence_template_id": template["id"]}, headers=admin_headers)
        r = client.get("/api/v1/cadence-tasks/my", headers=admin_headers)
        assert r.status_code == 200
        assert all(t["lead_id"] != lead["id"] for t in r.json())


class TestCadenceStepTypesAndSkipWeekends:
    """BREAK/FOLLOW_UP as step types, and CadenceStep.skip_weekends — see
    crm_service._compute_due_date()."""

    def test_break_and_follow_up_steps_are_accepted(self, client, admin_headers):
        steps = [
            {"step_order": 1, "step_type": "CALL", "subject": "Intro call", "wait_days": 0},
            {"step_order": 2, "step_type": "BREAK", "subject": "Cool-off period", "wait_days": 2},
            {"step_order": 3, "step_type": "FOLLOW_UP", "subject": "Check back in", "wait_days": 0},
        ]
        template = _template(client, admin_headers, steps)
        by_order = {s["step_order"]: s for s in template["steps"]}
        assert by_order[2]["step_type"] == "BREAK"
        assert by_order[3]["step_type"] == "FOLLOW_UP"
        # existing CALL/EMAIL/LINKEDIN behavior is untouched by the new types
        assert by_order[1]["step_type"] == "CALL"

    def test_skip_weekends_defaults_false_and_round_trips_true(self, client, admin_headers):
        template = _template(client, admin_headers, [
            {"step_order": 1, "step_type": "CALL", "subject": "Intro call", "wait_days": 1},
        ])
        assert template["steps"][0]["skip_weekends"] is False  # regression: default unchanged

        r = client.post(f"/api/v1/cadence-templates/{template['id']}/steps",
                        json={"step_order": 2, "step_type": "EMAIL", "subject": "Follow-up",
                              "wait_days": 5, "skip_weekends": True},
                        headers=admin_headers)
        assert r.status_code == 201, r.text
        assert r.json()["skip_weekends"] is True

    def test_enroll_due_date_uses_calendar_days_by_default(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        template = _template(client, admin_headers, [
            {"step_order": 1, "step_type": "CALL", "subject": "Intro call", "wait_days": 5,
             "skip_weekends": False},
        ])
        r = client.post(f"/api/v1/leads/{lead['id']}/cadence/enroll",
                        json={"cadence_template_id": template["id"]}, headers=admin_headers)
        assert r.status_code == 201, r.text
        due = date.fromisoformat(r.json()["tasks"][0]["due_date"])
        assert due == date.today() + timedelta(days=5)

    def test_enroll_due_date_skips_weekends_when_configured(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        template = _template(client, admin_headers, [
            {"step_order": 1, "step_type": "CALL", "subject": "Intro call", "wait_days": 5,
             "skip_weekends": True},
        ])
        r = client.post(f"/api/v1/leads/{lead['id']}/cadence/enroll",
                        json={"cadence_template_id": template["id"]}, headers=admin_headers)
        assert r.status_code == 201, r.text
        due = date.fromisoformat(r.json()["tasks"][0]["due_date"])
        assert due.weekday() < 5  # never lands on a Saturday/Sunday
        assert due == _add_business_days(date.today(), 5)

    def test_next_step_due_date_also_honors_skip_weekends(self, client, admin_headers):
        """The shared due-date function is used by BOTH enroll_lead_in_cadence()
        and complete_cadence_task() — this proves the second call site too."""
        lead = _lead(client, admin_headers)
        template = _template(client, admin_headers, [
            {"step_order": 1, "step_type": "CALL", "subject": "Intro call", "wait_days": 0},
            {"step_order": 2, "step_type": "EMAIL", "subject": "Follow-up", "wait_days": 6,
             "skip_weekends": True},
        ])
        enrolled = client.post(f"/api/v1/leads/{lead['id']}/cadence/enroll",
                               json={"cadence_template_id": template["id"]}, headers=admin_headers).json()
        first_task_id = enrolled["tasks"][0]["id"]
        client.post(f"/api/v1/cadence-tasks/{first_task_id}/complete",
                   json={"outcome_status": "DONE"}, headers=admin_headers)

        r = client.get(f"/api/v1/leads/{lead['id']}/cadence", headers=admin_headers)
        second_task = next(t for t in r.json()["tasks"] if t["id"] != first_task_id)
        due = date.fromisoformat(second_task["due_date"])
        assert due.weekday() < 5
        assert due == _add_business_days(date.today(), 6)


class TestCadenceAutoResolvedField:
    def test_manually_completed_task_is_not_auto_resolved(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        template = _template(client, admin_headers, TWO_STEPS)
        enrolled = client.post(f"/api/v1/leads/{lead['id']}/cadence/enroll",
                               json={"cadence_template_id": template["id"]}, headers=admin_headers).json()
        assert enrolled["tasks"][0]["auto_resolved"] is False  # regression: new field defaults false

        first_task_id = enrolled["tasks"][0]["id"]
        r = client.post(f"/api/v1/cadence-tasks/{first_task_id}/complete",
                        json={"outcome_status": "DONE"}, headers=admin_headers)
        assert r.json()["auto_resolved"] is False  # a rep completed it -- not the scheduler


class TestCadenceScheduler:
    """POST /cadence/advance-due-steps -- see
    crm_service.advance_due_cadence_steps()/require_cadence_scheduler_secret."""

    def _break_then_email(self, client, admin_headers, break_wait_days=0):
        lead = _lead(client, admin_headers)
        template = _template(client, admin_headers, [
            {"step_order": 1, "step_type": "BREAK", "subject": "Cool-off period",
             "wait_days": break_wait_days},
            {"step_order": 2, "step_type": "EMAIL", "subject": "Follow-up email", "wait_days": 0},
        ])
        enrolled = client.post(f"/api/v1/leads/{lead['id']}/cadence/enroll",
                               json={"cadence_template_id": template["id"]}, headers=admin_headers).json()
        return lead, template, enrolled

    def _call_then_follow_up(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        template = _template(client, admin_headers, [
            {"step_order": 1, "step_type": "CALL", "subject": "Intro call", "wait_days": 0},
            {"step_order": 2, "step_type": "FOLLOW_UP", "subject": "Check back in", "wait_days": 0},
        ])
        enrolled = client.post(f"/api/v1/leads/{lead['id']}/cadence/enroll",
                               json={"cadence_template_id": template["id"]}, headers=admin_headers).json()
        call_task_id = enrolled["tasks"][0]["id"]
        r = client.post(f"/api/v1/cadence-tasks/{call_task_id}/complete",
                        json={"outcome_status": "DONE"}, headers=admin_headers)
        assert r.status_code == 200, r.text
        detail = client.get(f"/api/v1/leads/{lead['id']}/cadence", headers=admin_headers).json()
        follow_up_task = next(t for t in detail["tasks"] if t["id"] != call_task_id)
        return lead, follow_up_task

    # --- auth ---

    def test_missing_secret_is_rejected(self, client):
        r = client.post("/api/v1/cadence/advance-due-steps")
        assert r.status_code == 401

    def test_wrong_secret_is_rejected(self, client):
        r = client.post("/api/v1/cadence/advance-due-steps",
                        headers={"X-Cadence-Scheduler-Secret": "not-the-real-secret"})
        assert r.status_code == 401

    def test_correct_secret_is_accepted(self, client):
        r = client.post("/api/v1/cadence/advance-due-steps", headers=_scheduler_headers())
        assert r.status_code == 200
        body = r.json()
        assert set(body) == {
            "breaks_resolved", "follow_ups_skipped", "follow_ups_left_pending", "enrollments_completed"}

    # --- BREAK auto-resolution ---

    def test_due_break_is_auto_resolved_and_advances(self, client, admin_headers):
        lead, _template, enrolled = self._break_then_email(client, admin_headers, break_wait_days=0)
        break_task_id = enrolled["tasks"][0]["id"]

        client.post("/api/v1/cadence/advance-due-steps", headers=_scheduler_headers())

        detail = client.get(f"/api/v1/leads/{lead['id']}/cadence", headers=admin_headers).json()
        break_task = next(t for t in detail["tasks"] if t["id"] == break_task_id)
        assert break_task["status"] == "DONE"
        assert break_task["auto_resolved"] is True
        assert detail["enrollment"]["current_step_order"] == 2
        assert detail["enrollment"]["status"] == "ACTIVE"
        new_task = next(t for t in detail["tasks"] if t["id"] != break_task_id)
        assert new_task["status"] == "PENDING"
        assert new_task["step_type"] == "EMAIL"

        # requirement: BREAK resolution never logs an outreach Communication
        comms = client.get(f"/api/v1/leads/{lead['id']}/communications", headers=admin_headers).json()
        assert all(c["source"] != "CADENCE" for c in comms)

    def test_not_yet_due_break_is_left_untouched(self, client, admin_headers):
        lead, _template, enrolled = self._break_then_email(client, admin_headers, break_wait_days=5)
        break_task_id = enrolled["tasks"][0]["id"]

        client.post("/api/v1/cadence/advance-due-steps", headers=_scheduler_headers())

        detail = client.get(f"/api/v1/leads/{lead['id']}/cadence", headers=admin_headers).json()
        break_task = next(t for t in detail["tasks"] if t["id"] == break_task_id)
        assert break_task["status"] == "PENDING"
        assert break_task["auto_resolved"] is False
        assert len(detail["tasks"]) == 1  # no next task created yet

    def test_completing_last_step_via_break_marks_enrollment_completed(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        template = _template(client, admin_headers, [
            {"step_order": 1, "step_type": "BREAK", "subject": "Final cool-off", "wait_days": 0},
        ])
        client.post(f"/api/v1/leads/{lead['id']}/cadence/enroll",
                   json={"cadence_template_id": template["id"]}, headers=admin_headers)

        client.post("/api/v1/cadence/advance-due-steps", headers=_scheduler_headers())

        detail = client.get(f"/api/v1/leads/{lead['id']}/cadence", headers=admin_headers).json()
        assert detail["enrollment"]["status"] == "COMPLETED"
        assert detail["enrollment"]["completed_at"] is not None

    # --- FOLLOW_UP reply handling ---

    def test_follow_up_auto_skipped_when_lead_already_replied(self, client, admin_headers):
        lead, follow_up_task = self._call_then_follow_up(client, admin_headers)
        _log_inbound_reply(client, admin_headers, lead["id"])

        client.post("/api/v1/cadence/advance-due-steps", headers=_scheduler_headers())

        detail = client.get(f"/api/v1/leads/{lead['id']}/cadence", headers=admin_headers).json()
        task = next(t for t in detail["tasks"] if t["id"] == follow_up_task["id"])
        assert task["status"] == "SKIPPED"
        assert task["auto_resolved"] is True
        assert detail["enrollment"]["status"] == "COMPLETED"  # FOLLOW_UP was the last step

    def test_follow_up_left_pending_when_no_reply(self, client, admin_headers):
        lead, follow_up_task = self._call_then_follow_up(client, admin_headers)
        # deliberately no _log_inbound_reply() call

        client.post("/api/v1/cadence/advance-due-steps", headers=_scheduler_headers())

        detail = client.get(f"/api/v1/leads/{lead['id']}/cadence", headers=admin_headers).json()
        task = next(t for t in detail["tasks"] if t["id"] == follow_up_task["id"])
        assert task["status"] == "PENDING"
        assert task["auto_resolved"] is False
        assert detail["enrollment"]["status"] == "ACTIVE"

        # "proceed normally" -- a rep can still complete it exactly like any
        # other real outreach step (regression: existing complete flow works)
        r = client.post(f"/api/v1/cadence-tasks/{task['id']}/complete",
                        json={"outcome_status": "DONE"}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["auto_resolved"] is False

    def test_reply_before_enrollment_does_not_retroactively_skip(self, client, admin_headers):
        """The reply must postdate the relevant previous activity -- an old
        reply logged before the CALL step doesn't count."""
        lead = _lead(client, admin_headers)
        _log_inbound_reply(client, admin_headers, lead["id"],
                           occurred_at=datetime.now(timezone.utc) - timedelta(days=30))
        template = _template(client, admin_headers, [
            {"step_order": 1, "step_type": "CALL", "subject": "Intro call", "wait_days": 0},
            {"step_order": 2, "step_type": "FOLLOW_UP", "subject": "Check back in", "wait_days": 0},
        ])
        enrolled = client.post(f"/api/v1/leads/{lead['id']}/cadence/enroll",
                               json={"cadence_template_id": template["id"]}, headers=admin_headers).json()
        call_task_id = enrolled["tasks"][0]["id"]
        client.post(f"/api/v1/cadence-tasks/{call_task_id}/complete",
                   json={"outcome_status": "DONE"}, headers=admin_headers)

        client.post("/api/v1/cadence/advance-due-steps", headers=_scheduler_headers())

        detail = client.get(f"/api/v1/leads/{lead['id']}/cadence", headers=admin_headers).json()
        follow_up_task = next(t for t in detail["tasks"] if t["id"] != call_task_id)
        assert follow_up_task["status"] == "PENDING"  # the 30-day-old reply predates the CALL

    # --- idempotency / concurrency ---

    def test_running_scheduler_twice_does_not_double_process(self, client, admin_headers):
        lead, _template, enrolled = self._break_then_email(client, admin_headers, break_wait_days=0)
        break_task_id = enrolled["tasks"][0]["id"]

        client.post("/api/v1/cadence/advance-due-steps", headers=_scheduler_headers())
        client.post("/api/v1/cadence/advance-due-steps", headers=_scheduler_headers())

        detail = client.get(f"/api/v1/leads/{lead['id']}/cadence", headers=admin_headers).json()
        assert len(detail["tasks"]) == 2  # no duplicate EMAIL task from the second run
        assert detail["enrollment"]["current_step_order"] == 2
        break_task = next(t for t in detail["tasks"] if t["id"] == break_task_id)
        assert break_task["status"] == "DONE"

    def test_scheduler_cannot_reprocess_a_task_a_rep_already_completed(self, client, admin_headers):
        """Simulates the "scheduler processes a PENDING task while a rep
        manually completes the same task" race via ordering: whichever side
        acts first wins, and the other must see CADENCE_TASK_NOT_PENDING /
        leave the row untouched rather than double-processing it. The actual
        mutual exclusion is CadenceTaskRepository.update_if()'s row lock
        (repositories/_base.py) -- this test asserts the resulting contract,
        not the lock itself."""
        lead, _template, enrolled = self._break_then_email(client, admin_headers, break_wait_days=0)
        break_task_id = enrolled["tasks"][0]["id"]

        # the rep wins the race this time
        r = client.post(f"/api/v1/cadence-tasks/{break_task_id}/complete",
                        json={"outcome_status": "DONE"}, headers=admin_headers)
        assert r.status_code == 200

        client.post("/api/v1/cadence/advance-due-steps", headers=_scheduler_headers())

        detail = client.get(f"/api/v1/leads/{lead['id']}/cadence", headers=admin_headers).json()
        assert len(detail["tasks"]) == 2  # scheduler did not create a second "next" task
        break_task = next(t for t in detail["tasks"] if t["id"] == break_task_id)
        assert break_task["auto_resolved"] is False  # the rep resolved it, not the scheduler
        assert detail["enrollment"]["current_step_order"] == 2

    def test_manual_complete_after_scheduler_already_resolved_is_rejected(self, client, admin_headers):
        """The other ordering of the same race: the scheduler wins first."""
        lead, _template, enrolled = self._break_then_email(client, admin_headers, break_wait_days=0)
        break_task_id = enrolled["tasks"][0]["id"]

        client.post("/api/v1/cadence/advance-due-steps", headers=_scheduler_headers())

        r = client.post(f"/api/v1/cadence-tasks/{break_task_id}/complete",
                        json={"outcome_status": "DONE"}, headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "CADENCE_TASK_NOT_PENDING"
