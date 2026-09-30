"""Contracts module (§1/§8) — agreements (incl. sign/supersede), clauses,
documents, reviews. Exercised against the real Postgres container.
"""
import uuid

from src.services.auth_service import mint_token_for_profiles


def _create_account(client, headers):
    r = client.post("/api/v1/accounts", json={"legal_name": "Contracts Test Co"}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create_agreement(client, headers, account_id, agreement_type="NDA", **overrides):
    payload = {"account_id": account_id, "agreement_type": agreement_type, "title": "Test Agreement"}
    payload.update(overrides)
    r = client.post("/api/v1/agreements", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _provision(client, admin_headers, full_name, role_code):
    """A real, role-linked employee — needed wherever a test wants
    verified_employee_uuid()/employee_ids_with_role() to actually resolve
    someone (the ae_headers/leadership_headers fixtures' ids are synthetic
    and don't correspond to a real employee row)."""
    suffix = uuid.uuid4().hex[:8]
    emp_id = client.post("/api/v1/admin/employees",
                        json={"email": f"{role_code.lower()}.{suffix}@example.com", "full_name": full_name},
                        headers=admin_headers).json()["id"]
    r = client.put(f"/api/v1/admin/employees/{emp_id}/profiles",
                   json={"profile_codes": [role_code]}, headers=admin_headers)
    assert r.status_code == 200, r.text
    token = mint_token_for_profiles(emp_id, {role_code})
    return emp_id, {"Authorization": f"Bearer {token}"}


class TestAgreements:
    def test_create_computes_sla_due_at_from_type(self, client, admin_headers, ae_headers):
        cust = _create_account(client, admin_headers)
        agr = _create_agreement(client, ae_headers, cust, agreement_type="MSA")
        assert agr["status"] == "DRAFT"
        assert agr["sla_due_at"] is not None

    def test_update_cannot_set_signed_directly(self, client, admin_headers, ae_headers):
        cust = _create_account(client, admin_headers)
        agr = _create_agreement(client, ae_headers, cust)
        r = client.patch(f"/api/v1/agreements/{agr['id']}", json={"status": "SIGNED"}, headers=ae_headers)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "USE_DEDICATED_ENDPOINT"

    def test_sign_then_cannot_sign_twice(self, client, admin_headers, ae_headers):
        cust = _create_account(client, admin_headers)
        agr = _create_agreement(client, ae_headers, cust)
        r = client.post(f"/api/v1/agreements/{agr['id']}/sign", headers=ae_headers)
        assert r.status_code == 200
        assert r.json()["status"] == "SIGNED"
        assert r.json()["signed_at"] is not None

        r = client.post(f"/api/v1/agreements/{agr['id']}/sign", headers=ae_headers)
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "ALREADY_SIGNED"

    def test_sales_cannot_sign(self, client, sales_headers):
        r = client.post("/api/v1/agreements/AGR-00001/sign", headers=sales_headers)
        assert r.status_code == 403

    def test_supersede_marks_old_superseded_and_creates_new_draft(self, client, admin_headers,
                                                                  ae_headers):
        cust = _create_account(client, admin_headers)
        agr = _create_agreement(client, ae_headers, cust)
        client.post(f"/api/v1/agreements/{agr['id']}/sign", headers=ae_headers)

        r = client.post(f"/api/v1/agreements/{agr['id']}/supersede",
                        json={"title": "Amended Agreement"}, headers=ae_headers)
        assert r.status_code == 201
        new_agr = r.json()
        assert new_agr["status"] == "DRAFT"
        assert new_agr["supersedes_agreement_id"] == agr["id"]
        assert new_agr["title"] == "Amended Agreement"

        old = client.get(f"/api/v1/agreements/{agr['id']}", headers=ae_headers).json()
        assert old["status"] == "SUPERSEDED"

    def test_delete_agreement(self, client, admin_headers, ae_headers):
        cust = _create_account(client, admin_headers)
        agr = _create_agreement(client, ae_headers, cust)
        r = client.delete(f"/api/v1/agreements/{agr['id']}", headers=admin_headers)
        assert r.status_code == 204
        assert client.get(f"/api/v1/agreements/{agr['id']}", headers=admin_headers).status_code == 404

    def test_sales_scope_blocks_agreement_and_subresources_for_unowned_account(
            self, client, admin_headers, ae_headers, sales_headers):
        # owner_employee_id is left unset, same as
        # test_crm.py::test_sales_scope_blocks_contacts_for_unowned_account.
        cust = _create_account(client, admin_headers)
        agr = _create_agreement(client, ae_headers, cust)

        r = client.get(f"/api/v1/agreements/{agr['id']}", headers=sales_headers)
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "FORBIDDEN"

        r = client.get("/api/v1/agreements", headers=sales_headers)
        assert r.status_code == 200
        assert agr["id"] not in {a["id"] for a in r.json()}

        # Every agreement-keyed sub-resource read inherits the same scope
        # check (the cascade the headline get_agreement()/list_agreements()
        # fix alone wouldn't have closed).
        for path in ("clauses", "documents", "reviews", "notes"):
            r = client.get(f"/api/v1/agreements/{agr['id']}/{path}", headers=sales_headers)
            assert r.status_code == 403, path
            assert r.json()["error"]["code"] == "FORBIDDEN"

        # AE (sees_all) is unaffected — clauses is a real (unaffected) table,
        # confirming the check doesn't block the owning side; `notes` is
        # deliberately not re-checked here since agreement_note doesn't
        # exist in this dev DB (see TestNotes below / CLAUDE.md).
        assert client.get(f"/api/v1/agreements/{agr['id']}", headers=ae_headers).status_code == 200
        assert client.get(f"/api/v1/agreements/{agr['id']}/clauses", headers=ae_headers).status_code == 200


class TestSignatureWorkflow:
    def test_send_for_signature_notifies_leadership(self, client, admin_headers, ae_headers):
        cust = _create_account(client, admin_headers)
        agr = _create_agreement(client, ae_headers, cust)
        _leader_id, leader_headers = _provision(client, admin_headers, "Test Leader", "LEADERSHIP")

        r = client.post(f"/api/v1/agreements/{agr['id']}/send-for-signature", headers=ae_headers)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "SENT"

        notifs = client.get("/api/v1/notifications", headers=leader_headers).json()
        matches = [n for n in notifs if n["agreement_id"] == agr["id"]
                  and n["notification_type"] == "AGREEMENT_PENDING_SIGNATURE"]
        assert matches, "expected a pending-signature notification for the leadership employee"
        assert matches[0]["message"]

    def test_leadership_can_sign(self, client, admin_headers, ae_headers):
        cust = _create_account(client, admin_headers)
        agr = _create_agreement(client, ae_headers, cust)
        _leader_id, leader_headers = _provision(client, admin_headers, "Test Leader 2", "LEADERSHIP")

        r = client.post(f"/api/v1/agreements/{agr['id']}/sign", headers=leader_headers)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "SIGNED"

    def test_sales_cannot_send_for_signature(self, client, sales_headers):
        r = client.post("/api/v1/agreements/AGR-00001/send-for-signature", headers=sales_headers)
        assert r.status_code == 403

    def test_sign_notifies_initiating_account_exec(self, client, admin_headers):
        _ae_id, ae_headers2 = _provision(client, admin_headers, "Test AE", "ACCOUNT_EXEC")
        cust = _create_account(client, admin_headers)
        agr = _create_agreement(client, ae_headers2, cust)

        r = client.post(f"/api/v1/agreements/{agr['id']}/sign", headers=admin_headers)
        assert r.status_code == 200, r.text

        notifs = client.get("/api/v1/notifications", headers=ae_headers2).json()
        matches = [n for n in notifs if n["agreement_id"] == agr["id"]
                  and n["notification_type"] == "AGREEMENT_SIGNED"]
        assert matches, "expected a signed notification for the initiating AE"


class TestClauses:
    def test_add_list_update_clause(self, client, admin_headers, ae_headers):
        cust = _create_account(client, admin_headers)
        agr = _create_agreement(client, ae_headers, cust)

        r = client.post(f"/api/v1/agreements/{agr['id']}/clauses",
                        json={"section_ref": "3.2", "clause_text": "Confidentiality clause"},
                        headers=ae_headers)
        assert r.status_code == 201
        clause_id = r.json()["id"]

        r = client.get(f"/api/v1/agreements/{agr['id']}/clauses", headers=ae_headers)
        assert r.status_code == 200
        assert len(r.json()) == 1

        r = client.patch(f"/api/v1/clauses/{clause_id}",
                         json={"is_flagged": True, "flag_reason": "Needs legal review"},
                         headers=ae_headers)
        assert r.status_code == 200
        assert r.json()["is_flagged"] is True


class TestDocuments:
    def test_document_version_increments(self, client, admin_headers, ae_headers):
        cust = _create_account(client, admin_headers)
        agr = _create_agreement(client, ae_headers, cust)

        r = client.post(f"/api/v1/agreements/{agr['id']}/documents",
                        json={"filename": "agreement_v1.pdf"}, headers=ae_headers)
        assert r.status_code == 201
        assert r.json()["version_number"] == 1

        r = client.post(f"/api/v1/agreements/{agr['id']}/documents",
                        json={"filename": "agreement_v2.pdf"}, headers=ae_headers)
        assert r.json()["version_number"] == 2

        r = client.get(f"/api/v1/agreements/{agr['id']}/documents", headers=ae_headers)
        assert len(r.json()) == 2


class TestReviews:
    def test_add_and_list_review(self, client, admin_headers, ae_headers):
        cust = _create_account(client, admin_headers)
        agr = _create_agreement(client, ae_headers, cust)

        r = client.post(f"/api/v1/agreements/{agr['id']}/reviews",
                        json={"outcome": "APPROVED", "summary": "Looks fine"}, headers=ae_headers)
        assert r.status_code == 201
        assert r.json()["outcome"] == "APPROVED"

        r = client.get(f"/api/v1/agreements/{agr['id']}/reviews", headers=ae_headers)
        assert r.status_code == 200
        assert len(r.json()) == 1


class TestNotes:
    def test_add_and_list_notes_with_commenter_and_timestamp(self, client, admin_headers, ae_headers):
        cust = _create_account(client, admin_headers)
        agr = _create_agreement(client, ae_headers, cust)

        r = client.post(f"/api/v1/agreements/{agr['id']}/notes",
                        json={"note_text": "Account asked for a 60-day term instead of 30."},
                        headers=ae_headers)
        assert r.status_code == 201
        note = r.json()
        assert note["note_text"] == "Account asked for a 60-day term instead of 30."
        assert note["created_at"] is not None
        assert note["created_by"] is not None

        r = client.post(f"/api/v1/agreements/{agr['id']}/notes",
                        json={"note_text": "Legal signed off on the amended term."},
                        headers=admin_headers)
        assert r.status_code == 201

        r = client.get(f"/api/v1/agreements/{agr['id']}/notes", headers=ae_headers)
        assert r.status_code == 200
        notes = r.json()
        assert len(notes) == 2
        assert [n["note_text"] for n in notes] == [
            "Account asked for a 60-day term instead of 30.",
            "Legal signed off on the amended term.",
        ]

    def test_sales_cannot_add_note(self, client, sales_headers):
        r = client.post("/api/v1/agreements/AGR-00001/notes",
                        json={"note_text": "should be forbidden"}, headers=sales_headers)
        assert r.status_code == 403

    def test_notes_no_longer_on_agreement_payload(self, client, admin_headers, ae_headers):
        cust = _create_account(client, admin_headers)
        agr = _create_agreement(client, ae_headers, cust)
        assert "notes" not in agr
