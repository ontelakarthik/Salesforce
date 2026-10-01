"""AI-assisted email drafting + call prep (BRD §5.6/§5.7) — crm_service.
generate_email_draft()/generate_call_prep(), backed by services/llm_client.py.
Both match a lead against the admin-configured Product catalog (see
test_products.py) rather than pitching generically.

No live web search backs any of this (nor web-enrichment, see
TestWebEnrichment* below) — Cohere retired their hosted web-search
connector on 2025-09-15 with no direct replacement, and adding a separate
search provider was explicitly deferred. Everything reasons from in-system
lead data plus whatever the model already knows.

This is the one place in the codebase that calls out over the network, so
everything runs via FastAPI's app.dependency_overrides rather than assuming
anything about the ambient environment — a dev doing manual testing may well
have a real COHERE_API_KEY in .env. The "not configured" 503 path is
simulated by overriding get_llm_client() to raise the same DomainError it
would if unconfigured; the happy path swaps in a fake that returns canned
JSON, exactly the pattern every other test uses real repos/DB for
everything else.

This is a persistent, shared Postgres DB with no per-test rollback — any
value a test filters/matches on (e.g. an "industry") must be unique per
test invocation (uuid4-suffixed), or a later re-run accumulates matches
from earlier runs and inflates counts.
"""
import json
import uuid

from src.server import app
from src.services.llm_client import get_llm_client
from src.utils.exceptions import DomainError


def _lead(client, headers, **overrides):
    payload = {"company_name": "Meridian Health", "contact_email": "test.lead@example.com", "first_name": "Ananya", "last_name": "Rao"} | overrides
    r = client.post("/api/v1/leads", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _override_llm(fake):
    app.dependency_overrides[get_llm_client] = lambda: fake


def _clear_llm_override():
    app.dependency_overrides.pop(get_llm_client, None)


class _FakeLLMClient:
    def __init__(self, response_text: str):
        self.response_text = response_text
        self.calls: list[tuple[str, str]] = []

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return self.response_text


def _override_llm_not_configured():
    """Simulates get_llm_client()'s own 503 without depending on whether a
    real COHERE_API_KEY happens to be in .env right now — a dev doing manual
    testing against a real key would otherwise make this suite's "not
    configured" path silently go live and hit the real API instead."""
    def _raise():
        raise DomainError(
            "AI_PROVIDER_NOT_CONFIGURED",
            "COHERE_API_KEY is not set — add it to .env to enable AI-assisted drafting.", 503)
    app.dependency_overrides[get_llm_client] = _raise


class TestNotConfigured:
    def teardown_method(self):
        _clear_llm_override()

    def test_email_draft_503s_when_no_api_key(self, client, admin_headers):
        _override_llm_not_configured()
        lead = _lead(client, admin_headers)
        r = client.post(f"/api/v1/leads/{lead['id']}/email-draft", headers=admin_headers)
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "AI_PROVIDER_NOT_CONFIGURED"

    def test_call_prep_503s_when_no_api_key(self, client, admin_headers):
        _override_llm_not_configured()
        lead = _lead(client, admin_headers)
        r = client.post(f"/api/v1/leads/{lead['id']}/call-prep", headers=admin_headers)
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "AI_PROVIDER_NOT_CONFIGURED"


class TestEmailDraftHappyPath:
    def teardown_method(self):
        _clear_llm_override()

    def test_generates_draft_from_fake_provider(self, client, admin_headers):
        fake = _FakeLLMClient(json.dumps({
            "subject": "Quick question", "body": "Hi there, ...", "matched_products": ["Widget Pro"],
        }))
        _override_llm(fake)
        lead = _lead(client, admin_headers, industry="Fintech", title="VP Engineering")

        r = client.post(f"/api/v1/leads/{lead['id']}/email-draft", headers=admin_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["subject"] == "Quick question"
        assert body["body"] == "Hi there, ..."
        assert body["grounded_in_replies"] == 0
        assert body["matched_products"] == ["Widget Pro"]
        assert len(fake.calls) == 1
        # the lead's own context should actually reach the prompt
        assert "Fintech" in fake.calls[0][1]
        assert "VP Engineering" in fake.calls[0][1]

    def test_active_product_catalog_reaches_the_prompt(self, client, admin_headers):
        product = client.post("/api/v1/products", json={
            "name": f"Catalog Match {uuid.uuid4()}", "description": "Solves exactly this problem.",
        }, headers=admin_headers).json()

        fake = _FakeLLMClient(json.dumps({"subject": "S", "body": "B", "matched_products": []}))
        _override_llm(fake)
        lead = _lead(client, admin_headers)

        r = client.post(f"/api/v1/leads/{lead['id']}/email-draft", headers=admin_headers)
        assert r.status_code == 200, r.text
        # the catalog lives in the system prompt, not the user prompt
        assert product["name"] in fake.calls[0][0]

    def test_matched_products_defaults_to_empty_list_when_omitted(self, client, admin_headers):
        _override_llm(_FakeLLMClient(json.dumps({"subject": "S", "body": "B"})))
        lead = _lead(client, admin_headers)

        r = client.post(f"/api/v1/leads/{lead['id']}/email-draft", headers=admin_headers)
        assert r.status_code == 200, r.text
        assert r.json()["matched_products"] == []

    def test_strips_markdown_code_fence(self, client, admin_headers):
        fenced = "```json\n" + json.dumps({"subject": "S", "body": "B"}) + "\n```"
        _override_llm(_FakeLLMClient(fenced))
        lead = _lead(client, admin_headers)

        r = client.post(f"/api/v1/leads/{lead['id']}/email-draft", headers=admin_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["subject"] == "S"
        assert body["body"] == "B"
        assert body["grounded_in_replies"] == 0

    def test_malformed_json_is_a_clean_502_not_a_500(self, client, admin_headers):
        _override_llm(_FakeLLMClient("not json at all"))
        lead = _lead(client, admin_headers)

        r = client.post(f"/api/v1/leads/{lead['id']}/email-draft", headers=admin_headers)
        assert r.status_code == 502
        assert r.json()["error"]["code"] == "AI_RESPONSE_INVALID"

    def test_missing_required_field_is_a_clean_502(self, client, admin_headers):
        _override_llm(_FakeLLMClient(json.dumps({"subject": "only a subject"})))
        lead = _lead(client, admin_headers)

        r = client.post(f"/api/v1/leads/{lead['id']}/email-draft", headers=admin_headers)
        assert r.status_code == 502
        assert r.json()["error"]["code"] == "AI_RESPONSE_INVALID"

    def test_grounds_in_past_replied_emails_in_same_industry(self, client, admin_headers):
        unique_industry = f"Aerospace-grounding-test-{uuid.uuid4()}"
        grounded_lead = _lead(client, admin_headers, industry=unique_industry)
        comm = client.post(f"/api/v1/leads/{grounded_lead['id']}/communications",
                          json={"direction": "OUTBOUND", "channel": "EMAIL", "subject": "Reusable rockets",
                               "occurred_at": "2026-02-01T10:00:00Z"}, headers=admin_headers).json()
        client.post(f"/api/v1/leads/{grounded_lead['id']}/communications/{comm['id']}/replied",
                   json={}, headers=admin_headers)

        fake = _FakeLLMClient(json.dumps({"subject": "S", "body": "B"}))
        _override_llm(fake)
        new_lead = _lead(client, admin_headers, industry=unique_industry)

        r = client.post(f"/api/v1/leads/{new_lead['id']}/email-draft", headers=admin_headers)
        assert r.status_code == 200, r.text
        assert r.json()["grounded_in_replies"] == 1
        assert "Reusable rockets" in fake.calls[0][1]

    def test_prior_touches_on_this_lead_reach_the_prompt(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        client.post(f"/api/v1/leads/{lead['id']}/communications",
                   json={"direction": "OUTBOUND", "channel": "EMAIL", "subject": "First outreach",
                        "occurred_at": "2026-02-01T10:00:00Z"}, headers=admin_headers)

        fake = _FakeLLMClient(json.dumps({"subject": "S", "body": "B"}))
        _override_llm(fake)
        r = client.post(f"/api/v1/leads/{lead['id']}/email-draft", headers=admin_headers)
        assert r.status_code == 200, r.text
        assert "First outreach" in fake.calls[0][1]

    def test_no_prior_touches_omits_the_timeline_section(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        fake = _FakeLLMClient(json.dumps({"subject": "S", "body": "B"}))
        _override_llm(fake)
        r = client.post(f"/api/v1/leads/{lead['id']}/email-draft", headers=admin_headers)
        assert r.status_code == 200, r.text
        assert "Prior touches" not in fake.calls[0][1]


class TestCallPrepHappyPath:
    def teardown_method(self):
        _clear_llm_override()

    def test_generates_call_prep_from_fake_provider(self, client, admin_headers):
        fake = _FakeLLMClient(json.dumps({
            "talking_points": ["point A", "point B"],
            "likely_objections": ["too expensive"],
            "opening_line": "Hi, got a minute?",
            "matched_products": ["Widget Pro"],
        }))
        _override_llm(fake)
        lead = _lead(client, admin_headers, industry="Retail")

        r = client.post(f"/api/v1/leads/{lead['id']}/call-prep", headers=admin_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["talking_points"] == ["point A", "point B"]
        assert body["likely_objections"] == ["too expensive"]
        assert body["opening_line"] == "Hi, got a minute?"
        assert body["matched_products"] == ["Widget Pro"]
        assert "Retail" in fake.calls[0][1]

    def test_matched_products_defaults_to_empty_list_when_omitted(self, client, admin_headers):
        _override_llm(_FakeLLMClient(json.dumps({
            "talking_points": ["a"], "likely_objections": ["b"], "opening_line": "c",
        })))
        lead = _lead(client, admin_headers)

        r = client.post(f"/api/v1/leads/{lead['id']}/call-prep", headers=admin_headers)
        assert r.status_code == 200, r.text
        assert r.json()["matched_products"] == []

    def test_prior_touches_on_this_lead_reach_the_prompt(self, client, admin_headers):
        lead = _lead(client, admin_headers)
        client.post(f"/api/v1/leads/{lead['id']}/communications",
                   json={"direction": "OUTBOUND", "channel": "CALL", "subject": "Left a voicemail",
                        "occurred_at": "2026-02-01T10:00:00Z"}, headers=admin_headers)

        fake = _FakeLLMClient(json.dumps({
            "talking_points": ["a"], "likely_objections": ["b"], "opening_line": "c",
        }))
        _override_llm(fake)
        r = client.post(f"/api/v1/leads/{lead['id']}/call-prep", headers=admin_headers)
        assert r.status_code == 200, r.text
        assert "Left a voicemail" in fake.calls[0][1]


class TestAIScope:
    def test_sales_cannot_generate_for_unowned_lead(self, client, admin_headers, sales_headers):
        lead = _lead(client, admin_headers)  # owner_employee_id left unset
        _override_llm(_FakeLLMClient(json.dumps({"subject": "S", "body": "B"})))
        try:
            r = client.post(f"/api/v1/leads/{lead['id']}/email-draft", headers=sales_headers)
            assert r.status_code == 403
        finally:
            _clear_llm_override()


class TestWebEnrichmentNotConfigured:
    def teardown_method(self):
        _clear_llm_override()

    def test_web_enrichment_503s_when_no_api_key(self, client, admin_headers):
        _override_llm_not_configured()
        lead = _lead(client, admin_headers)
        r = client.post(f"/api/v1/leads/{lead['id']}/web-enrichment", headers=admin_headers)
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "AI_PROVIDER_NOT_CONFIGURED"


class TestWebEnrichmentHappyPath:
    def teardown_method(self):
        _clear_llm_override()

    def test_generates_enrichment_and_updates_lead_score(self, client, admin_headers):
        fake = _FakeLLMClient(json.dumps({
            "funding_signal": True, "hiring_signal": False, "growth_signal": True,
            "headlines": ["Acme raised a Series A"], "score_points": 20,
            "summary": "Acme recently raised a Series A round.",
        }))
        _override_llm(fake)
        lead = _lead(client, admin_headers, company_name="Acme Rockets")

        r = client.post(f"/api/v1/leads/{lead['id']}/web-enrichment", headers=admin_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["funding_signal"] is True
        assert body["hiring_signal"] is False
        assert body["growth_signal"] is True
        assert body["headlines"] == ["Acme raised a Series A"]
        assert body["score_points"] == 20
        assert body["summary"] == "Acme recently raised a Series A round."
        assert body["lead_score"] == 20
        assert "Acme Rockets" in fake.calls[0][1]

        detail = client.get(f"/api/v1/leads/{lead['id']}", headers=admin_headers).json()
        assert detail["web_enrichment_points"] == 20
        assert detail["web_enrichment_summary"] == "Acme recently raised a Series A round."
        assert detail["web_enrichment_at"] is not None
        assert detail["lead_score"] == 20

    def test_combines_with_rule_based_score(self, client, admin_headers):
        unique_industry = f"WebEnrichCombine-{uuid.uuid4()}"
        rule = client.post("/api/v1/lead-scoring-rules", json={
            "name": f"industry rule {uuid.uuid4()}", "field_name": "industry", "operator": "EQUALS",
            "comparison_value": unique_industry, "points": 15,
        }, headers=admin_headers)
        assert rule.status_code == 201, rule.text

        lead = _lead(client, admin_headers, industry=unique_industry)
        assert lead["lead_score"] == 15

        _override_llm(_FakeLLMClient(json.dumps({
            "funding_signal": False, "hiring_signal": True, "growth_signal": False,
            "headlines": [], "score_points": 10, "summary": "Hiring for several roles.",
        })))
        r = client.post(f"/api/v1/leads/{lead['id']}/web-enrichment", headers=admin_headers)
        assert r.status_code == 200, r.text
        assert r.json()["lead_score"] == 25

    def test_clamps_score_points_above_30(self, client, admin_headers):
        _override_llm(_FakeLLMClient(json.dumps({
            "funding_signal": False, "hiring_signal": False, "growth_signal": False,
            "headlines": [], "score_points": 999, "summary": "huge score",
        })))
        lead = _lead(client, admin_headers)

        r = client.post(f"/api/v1/leads/{lead['id']}/web-enrichment", headers=admin_headers)
        assert r.status_code == 200, r.text
        assert r.json()["score_points"] == 30
        assert r.json()["lead_score"] == 30

    def test_clamps_negative_score_points_to_0(self, client, admin_headers):
        _override_llm(_FakeLLMClient(json.dumps({
            "funding_signal": False, "hiring_signal": False, "growth_signal": False,
            "headlines": [], "score_points": -5, "summary": "nothing found",
        })))
        lead = _lead(client, admin_headers)

        r = client.post(f"/api/v1/leads/{lead['id']}/web-enrichment", headers=admin_headers)
        assert r.status_code == 200, r.text
        assert r.json()["score_points"] == 0
        assert r.json()["lead_score"] == 0

    def test_malformed_response_is_a_clean_502(self, client, admin_headers):
        _override_llm(_FakeLLMClient("not json at all"))
        lead = _lead(client, admin_headers)

        r = client.post(f"/api/v1/leads/{lead['id']}/web-enrichment", headers=admin_headers)
        assert r.status_code == 502
        assert r.json()["error"]["code"] == "AI_RESPONSE_INVALID"

    def test_missing_required_field_is_a_clean_502(self, client, admin_headers):
        _override_llm(_FakeLLMClient(json.dumps({"summary": "only a summary"})))
        lead = _lead(client, admin_headers)

        r = client.post(f"/api/v1/leads/{lead['id']}/web-enrichment", headers=admin_headers)
        assert r.status_code == 502
        assert r.json()["error"]["code"] == "AI_RESPONSE_INVALID"

    def test_reenrichment_replaces_web_component_not_rule(self, client, admin_headers):
        unique_industry = f"WebEnrichReenrich-{uuid.uuid4()}"
        rule = client.post("/api/v1/lead-scoring-rules", json={
            "name": f"industry rule {uuid.uuid4()}", "field_name": "industry", "operator": "EQUALS",
            "comparison_value": unique_industry, "points": 10,
        }, headers=admin_headers)
        assert rule.status_code == 201, rule.text
        lead = _lead(client, admin_headers, industry=unique_industry)
        assert lead["lead_score"] == 10

        _override_llm(_FakeLLMClient(json.dumps({
            "funding_signal": True, "hiring_signal": False, "growth_signal": False,
            "headlines": [], "score_points": 20, "summary": "first pass",
        })))
        first = client.post(f"/api/v1/leads/{lead['id']}/web-enrichment", headers=admin_headers)
        assert first.json()["lead_score"] == 30

        _override_llm(_FakeLLMClient(json.dumps({
            "funding_signal": False, "hiring_signal": False, "growth_signal": False,
            "headlines": [], "score_points": 5, "summary": "second pass, less exciting",
        })))
        second = client.post(f"/api/v1/leads/{lead['id']}/web-enrichment", headers=admin_headers)
        assert second.status_code == 200, second.text
        assert second.json()["score_points"] == 5
        assert second.json()["lead_score"] == 15  # 10 (rule) + 5 (new web) — not 10+20+5


class TestWebEnrichmentScope:
    def test_sales_cannot_generate_for_unowned_lead(self, client, admin_headers, sales_headers):
        lead = _lead(client, admin_headers)  # owner_employee_id left unset
        _override_llm(_FakeLLMClient(json.dumps({
            "funding_signal": False, "hiring_signal": False, "growth_signal": False,
            "headlines": [], "score_points": 0, "summary": "n/a",
        })))
        try:
            r = client.post(f"/api/v1/leads/{lead['id']}/web-enrichment", headers=sales_headers)
            assert r.status_code == 403
        finally:
            _clear_llm_override()
