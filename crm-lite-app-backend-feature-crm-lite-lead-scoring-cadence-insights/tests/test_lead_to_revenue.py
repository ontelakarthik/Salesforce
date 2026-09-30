"""End-to-end proof of the proposed flow: Campaign -> Lead -> Convert ->
Won Opportunity -> Project -> SOW (governed by an MSA) -> a milestone gets
invoiced -> Order + Revenue Recognition, with the recognized revenue traced
all the way back to the originating Campaign. This is the "Meridian Health"
worked example, made real against the live Postgres container rather than
just described in the architecture proposal.

Every other test file exercises one module in isolation; this one is the
one place that walks the full pipeline in a single test, since that's the
whole point of the feature — that attribution survives the entire journey.
"""


def test_campaign_to_revenue_end_to_end(client, admin_headers, ae_headers):
    # 1. Campaign
    campaign = client.post("/api/v1/campaigns",
                           json={"name": "Healthcare Data Modernization Webinar",
                                 "campaign_type": "WEBINAR"},
                           headers=admin_headers).json()

    # 2. Lead, captured from the webinar, then qualified
    lead = client.post("/api/v1/leads",
                       json={"company_name": "Meridian Health", "first_name": "Ananya", "last_name": "Rao",
                             "contact_email": "ananya@meridianhealth.example",
                             "campaign_id": campaign["id"], "source": "Webinar"},
                       headers=admin_headers).json()
    for status in ["ATTEMPTING_CONTACT", "CONTACTED", "QUALIFYING", "QUALIFIED"]:
        r = client.patch(f"/api/v1/leads/{lead['id']}", json={"status": status}, headers=admin_headers)
        assert r.status_code == 200, r.text

    # 3. Convert -> Account + Contact + Opportunity together
    converted = client.post(f"/api/v1/leads/{lead['id']}/convert",
                            json={"opportunity_name": "Meridian Health — Data Platform Modernization",
                                  "estimated_value": 200000}, headers=admin_headers).json()
    account_id = converted["converted_account_id"]
    opportunity_id = converted["converted_opportunity_id"]

    # 4. The deal runs its normal course to Won.
    r = client.patch(f"/api/v1/opportunities/{opportunity_id}", json={"stage": "WON"}, headers=ae_headers)
    assert r.status_code == 200, r.text

    # 5. MSA signed first.
    msa = client.post("/api/v1/agreements",
                      json={"account_id": account_id, "agreement_type": "MSA", "title": "Meridian MSA"},
                      headers=ae_headers).json()

    # 6. Won opportunity becomes a Project.
    project = client.post("/api/v1/projects",
                          json={"opportunity_id": opportunity_id, "name": "Meridian Data Platform",
                                "start_date": "2026-03-01"},
                          headers=ae_headers).json()
    assert project["account_id"] == account_id  # inherited from the opportunity, not client-supplied

    # 7. SOW, governed by that MSA, linked to that Project.
    sow = client.post("/api/v1/agreements",
                      json={"account_id": account_id, "agreement_type": "SOW", "title": "Meridian SOW"},
                      headers=ae_headers).json()
    r = client.patch(f"/api/v1/agreements/{sow['id']}/sow-detail",
                     json={"project_id": project["id"], "governing_msa_id": msa["id"]},
                     headers=admin_headers)
    assert r.status_code == 200, r.text

    # 8. A milestone is delivered and invoiced.
    milestone = client.post(f"/api/v1/agreements/{sow['id']}/milestones",
                            json={"milestone_name": "Design sign-off", "planned_date": "2026-04-01",
                                  "amount": 45000}, headers=admin_headers).json()
    client.patch(f"/api/v1/milestones/{milestone['id']}", json={"status": "DELIVERED"}, headers=admin_headers)
    r = client.patch(f"/api/v1/milestones/{milestone['id']}",
                     json={"status": "INVOICED", "invoice_ref": "INV-2026-0091"}, headers=admin_headers)
    assert r.status_code == 200

    # 9. Revenue is now a real, traceable number — not a text field.
    revenue = client.get(f"/api/v1/agreements/{sow['id']}/revenue-recognition", headers=admin_headers).json()
    assert len(revenue) == 1
    entry = revenue[0]
    assert float(entry["recognized_amount"]) == 45000.0
    assert entry["account_id"] == account_id
    # The whole point: this dollar traces back through the Project and the
    # Won Opportunity to the Campaign that originated it, 8 steps upstream.
    assert entry["opportunity_id"] == opportunity_id
    assert entry["campaign_id"] == campaign["id"]

    orders = client.get(f"/api/v1/agreements/{sow['id']}/orders", headers=admin_headers).json()
    assert len(orders) == 1
    assert orders[0]["id"] == entry["order_id"]

    # 10. It also created an Asset — "what Meridian now owns" — and traced
    # its campaign the same way. Visible from the Account's own Assets list.
    assets = client.get(f"/api/v1/accounts/{account_id}/assets", headers=admin_headers).json()
    assert len(assets) == 1
    asset = assets[0]
    assert asset["campaign_id"] == campaign["id"]
    assert asset["renewed_by_opportunity_id"] is None  # nobody's renewed it yet
    assert orders[0]["asset_id"] == asset["id"]
    assert entry["asset_id"] == asset["id"]

    # 11. A second milestone on the *same* SOW reuses the same Asset — it's
    # one Asset per engagement, not one per invoice.
    milestone2 = client.post(f"/api/v1/agreements/{sow['id']}/milestones",
                             json={"milestone_name": "Beta", "planned_date": "2026-06-01",
                                   "amount": 30000}, headers=admin_headers).json()
    client.patch(f"/api/v1/milestones/{milestone2['id']}", json={"status": "DELIVERED"}, headers=admin_headers)
    client.patch(f"/api/v1/milestones/{milestone2['id']}",
                 json={"status": "INVOICED", "invoice_ref": "INV-2026-0114"}, headers=admin_headers)
    assets_after = client.get(f"/api/v1/accounts/{account_id}/assets", headers=admin_headers).json()
    assert len(assets_after) == 1
    assert assets_after[0]["id"] == asset["id"]
    revenue_after = client.get(f"/api/v1/agreements/{sow['id']}/revenue-recognition", headers=admin_headers).json()
    assert len(revenue_after) == 2
    assert {r["asset_id"] for r in revenue_after} == {asset["id"]}

    # 12. Ten months later: a Phase 2 renewal starts from this Asset, not
    # from zero — the ERD's dashed "renewal / cross-sell" arrow, made real.
    renewal = client.post("/api/v1/opportunities",
                          json={"account_id": account_id, "name": "Meridian Health — Phase 2 Analytics",
                                "estimated_value": 120000, "originating_asset_id": asset["id"]},
                          headers=ae_headers).json()
    assert renewal["originating_asset_id"] == asset["id"]
    # Inherited automatically from the Asset — nobody had to remember or
    # re-enter which campaign this account originally came from.
    assert renewal["campaign_id"] == campaign["id"]

    asset_after_renewal = client.get(f"/api/v1/accounts/{account_id}/assets", headers=admin_headers).json()[0]
    assert asset_after_renewal["renewed_by_opportunity_id"] == renewal["id"]
