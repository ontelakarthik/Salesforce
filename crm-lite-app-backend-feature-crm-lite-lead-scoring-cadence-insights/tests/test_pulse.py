"""Pulse — signal sourcing, Radar worklist, next-best-action (crm_service's
ingest_signals()/get_radar()/list_lead_signals()/generate_next_best_action()).

Same persistent, no-per-test-rollback Postgres as every other test module
(see test_ai_drafting.py's docstring) — ingest_signals() sources from a
FIXED mock catalog (crm_service._MOCK_SIGNAL_CATALOG), not a per-test
parameterized one, so these tests key off the catalog's own well-known
company names (e.g. "Solvane Health") rather than uuid-suffixed ones, and
lean on ingest's own dedup (SignalRepository.exists()) to stay idempotent
across repeated runs of this suite against the same database.
"""
from src.server import app
from src.services.llm_client import get_optional_llm_client


def _ingest(client, headers, since_days=90):
    r = client.post(f"/api/v1/pulse/ingest?since_days={since_days}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _radar(client, headers, **params):
    r = client.get("/api/v1/pulse/radar", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _lead_by_company(client, headers, company_name):
    r = client.get("/api/v1/leads", headers=headers)
    assert r.status_code == 200, r.text
    matches = [lead for lead in r.json() if lead["company_name"] == company_name]
    assert matches, f"no lead found for {company_name!r} — did ingest run?"
    return matches[0]


class TestIngest:
    def test_ingest_creates_leads_and_signals(self, client, admin_headers):
        # signals_ingested may legitimately be 0 here: this suite runs
        # against a persistent, no-per-test-rollback database (see the
        # module docstring), so a prior run of this same test may already
        # have sourced the whole fixed catalog. The real invariant —
        # regardless of which run actually did the sourcing — is that the
        # lead exists with a positive score from it.
        result = _ingest(client, admin_headers)
        assert result["signals_ingested"] >= 0
        assert set(result["sources_run"]) <= {
            "LinkedIn Jobs", "SAM.gov", "BuiltWith", "Crunchbase", "SEC EDGAR", "PR Newswire", "Company Blog",
        }
        lead = _lead_by_company(client, admin_headers, "Solvane Health")
        assert lead["lead_score"] >= 1
        assert lead["signal_points"] is not None and lead["signal_points"] >= 1

    def test_ingest_is_idempotent(self, client, admin_headers):
        _ingest(client, admin_headers)
        first_signals = client.get(
            "/api/v1/leads/" + _lead_by_company(client, admin_headers, "Solvane Health")["id"] + "/signals",
            headers=admin_headers,
        ).json()
        second = _ingest(client, admin_headers)
        assert second["signals_ingested"] == 0  # every catalog entry already sourced
        second_signals = client.get(
            "/api/v1/leads/" + _lead_by_company(client, admin_headers, "Solvane Health")["id"] + "/signals",
            headers=admin_headers,
        ).json()
        assert len(second_signals) == len(first_signals)

    def test_ingest_respects_since_days(self, client, admin_headers):
        # The oldest mock entries are ~40 days old — a 1-day window sources
        # only same-day signals (RFP entries at age_days=1/2), never those.
        result = _ingest(client, admin_headers, since_days=1)
        assert result["signals_ingested"] <= 2


class TestRadar:
    def test_radar_only_lists_leads_with_signals(self, client, admin_headers):
        _ingest(client, admin_headers)
        rows = _radar(client, admin_headers)
        assert rows, "expected at least one Radar row after ingest"
        for row in rows:
            assert row["signal_count"] >= 1
            assert row["grade"] in {"A", "B", "C", "D"}
            assert row["why_now"]

    def test_radar_sorted_by_score_descending(self, client, admin_headers):
        _ingest(client, admin_headers)
        rows = _radar(client, admin_headers)
        scores = [row["lead_score"] for row in rows]
        assert scores == sorted(scores, reverse=True)

    def test_radar_min_score_filter(self, client, admin_headers):
        _ingest(client, admin_headers)
        all_rows = _radar(client, admin_headers)
        high_bar = max((r["lead_score"] for r in all_rows), default=0) + 1
        assert _radar(client, admin_headers, min_score=high_bar) == []

    def test_radar_practice_filter(self, client, admin_headers):
        _ingest(client, admin_headers)
        rows = _radar(client, admin_headers, practice="Cybersecurity")
        assert all(row["recommended_practice"] == "Cybersecurity" for row in rows)


class TestLeadSignals:
    def test_lists_signals_newest_first_with_decayed_points(self, client, admin_headers):
        _ingest(client, admin_headers)
        lead = _lead_by_company(client, admin_headers, "Northfall Logistics")
        r = client.get(f"/api/v1/leads/{lead['id']}/signals", headers=admin_headers)
        assert r.status_code == 200, r.text
        signals = r.json()
        assert len(signals) >= 2
        captured_ats = [s["captured_at"] for s in signals]
        assert captured_ats == sorted(captured_ats, reverse=True)
        for s in signals:
            assert 0 <= s["score_points"] <= 40


class TestNextBestActionFallback:
    def teardown_method(self):
        app.dependency_overrides.pop(get_optional_llm_client, None)

    def test_falls_back_without_ai_key(self, client, admin_headers):
        """No override at all — get_optional_llm_client() itself returns
        None when COHERE_API_KEY isn't set (see llm_client.py), so this
        exercises the real dependency, not a fake."""
        _ingest(client, admin_headers)
        lead = _lead_by_company(client, admin_headers, "Ironbridge Robotics")
        r = client.post(f"/api/v1/leads/{lead['id']}/next-best-action", headers=admin_headers)
        assert r.status_code == 200, r.text
        nba = r.json()
        assert nba["source"] == "fallback"
        assert nba["channel"] in {"EMAIL", "CALL", "LINKEDIN"}
        assert 1 <= nba["due_in_days"] <= 14
        assert nba["why_now"]


class TestNextBestActionAI:
    def teardown_method(self):
        app.dependency_overrides.pop(get_optional_llm_client, None)

    def test_uses_ai_response_when_configured(self, client, admin_headers):
        import json

        class _FakeLLMClient:
            def complete(self, system_prompt: str, user_prompt: str) -> str:
                return json.dumps({
                    "action": "Call about their RFP.", "channel": "call",
                    "why_now": "They just issued an RFP.", "due_in_days": 1,
                })

        app.dependency_overrides[get_optional_llm_client] = lambda: _FakeLLMClient()
        _ingest(client, admin_headers)
        lead = _lead_by_company(client, admin_headers, "Halcyon Financial")
        r = client.post(f"/api/v1/leads/{lead['id']}/next-best-action", headers=admin_headers)
        assert r.status_code == 200, r.text
        nba = r.json()
        assert nba["source"] == "ai"
        assert nba["channel"] == "CALL"  # normalized to upper-case, validated against the enum
        assert nba["due_in_days"] == 1

    def test_ai_failure_falls_back_gracefully(self, client, admin_headers):
        class _BrokenLLMClient:
            def complete(self, system_prompt: str, user_prompt: str) -> str:
                return "not json at all"

        app.dependency_overrides[get_optional_llm_client] = lambda: _BrokenLLMClient()
        _ingest(client, admin_headers)
        lead = _lead_by_company(client, admin_headers, "Vermilion Manufacturing")
        r = client.post(f"/api/v1/leads/{lead['id']}/next-best-action", headers=admin_headers)
        assert r.status_code == 200, r.text  # never a 502 — Radar's core feature degrades, doesn't fail
        assert r.json()["source"] == "fallback"


class TestScoreComposition:
    def test_editing_a_lead_never_drops_its_signal_points(self, client, admin_headers):
        """Regression test for the exact bug class web_enrichment_points was
        already guarded against: update_lead() must fold row.signal_points
        back into lead_score, not silently zero it out on an unrelated
        field edit (see crm_service.update_lead())."""
        _ingest(client, admin_headers)
        lead = _lead_by_company(client, admin_headers, "Driftwood Media")
        assert lead["signal_points"]
        r = client.patch(
            f"/api/v1/leads/{lead['id']}", json={"industry": "Media & Entertainment"}, headers=admin_headers)
        assert r.status_code == 200, r.text
        updated = r.json()
        assert updated["signal_points"] == lead["signal_points"]
        assert updated["lead_score"] >= lead["signal_points"]
