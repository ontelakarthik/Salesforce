"""One-off diagnostic: exercise the live Territory/Role-Hierarchy/Lead-email
feature set against the deployed backend, exactly like a real browser
session would. Mints the token in-process (never prints the JWT secret),
creates real rows over HTTPS, confirms persistence via re-fetch, and cleans
up everything it created.
"""
import uuid

import httpx

from src.repositories.admin_repository import get_employee_repository
from src.services.auth_service import _role_codes_for_employee, mint_token_for_profiles

emp = get_employee_repository().find_by_email("vikram.tagirisepu@tachyontech.com")
if emp is None:
    print("admin employee not found")
    raise SystemExit(0)

role_codes = _role_codes_for_employee(emp.id)
token = mint_token_for_profiles(str(emp.id), set(role_codes))
headers = {"Authorization": f"Bearer {token}"}
base = "https://crm-lite-backend-819750641834.asia-south1.run.app/api/v1"

failures = []
cleanup = {"employees": [], "profiles": [], "accounts": [], "leads": [], "campaigns": []}


def check(label, condition, detail=""):
    status = "OK" if condition else "FAIL"
    print(f"[{status}] {label} {detail}")
    if not condition:
        failures.append(label)


with httpx.Client(headers=headers, timeout=30) as c:
    # --- Territory lookup seeded ---
    r = c.get(f"{base}/admin/lookups/territory")
    check("territory lookup reachable", r.status_code == 200, f"-> {r.status_code}")
    codes = {row["code"] for row in r.json()} if r.status_code == 200 else set()
    check("USA/CANADA territories seeded", {"USA", "CANADA"} <= codes, f"got {codes}")

    # --- Employee territory assignment ---
    r = c.post(f"{base}/admin/employees", json={
        "email": f"smoke.territory.{uuid.uuid4().hex[:8]}@example.invalid",
        "full_name": "Smoke Territory Rep", "territory": "USA",
    })
    check("create employee with territory", r.status_code == 201, f"-> {r.status_code} {r.text[:300]}")
    rep = r.json() if r.status_code == 201 else None
    if rep:
        cleanup["employees"].append(rep["id"])
        check("employee territory persisted", rep.get("territory") == "USA", f"got {rep.get('territory')!r}")

    # --- Lead email now required ---
    r = c.post(f"{base}/leads", json={"company_name": "Smoke No Email Co", "last_name": "Doe"})
    check("lead without email rejected", r.status_code == 422, f"-> {r.status_code}")

    r = c.post(f"{base}/leads", json={
        "company_name": "Smoke Lead Co", "last_name": "Doe",
        "contact_email": "smoke.lead@example.invalid", "owner_employee_id": rep["id"] if rep else None,
    })
    check("lead with email + owner created", r.status_code == 201, f"-> {r.status_code} {r.text[:300]}")
    lead = r.json() if r.status_code == 201 else None
    if lead:
        cleanup["leads"].append(lead["id"])
        check("lead defaults to owner's territory", lead.get("territory") == "USA", f"got {lead.get('territory')!r}")

    # --- Account territory defaulting ---
    r = c.post(f"{base}/accounts", json={
        "legal_name": "Smoke Territory Account", "owner_employee_id": rep["id"] if rep else None,
    })
    check("account created", r.status_code == 201, f"-> {r.status_code} {r.text[:300]}")
    account = r.json() if r.status_code == 201 else None
    if account:
        cleanup["accounts"].append(account["id"])
        check("account defaults to owner's territory", account.get("territory") == "USA", f"got {account.get('territory')!r}")

    # --- Campaign OWD preserved as PUBLIC_READ_WRITE (not reverted to PRIVATE) ---
    r = c.get(f"{base}/org-wide-defaults")
    check("org-wide-defaults reachable", r.status_code == 200, f"-> {r.status_code}")
    if r.status_code == 200:
        campaign_owd = r.json()["defaults"].get("CAMPAIGN")
        check("campaign OWD still PUBLIC_READ_WRITE", campaign_owd == "PUBLIC_READ_WRITE", f"got {campaign_owd!r}")

    # --- Communication body persists ---
    if lead:
        r = c.post(f"{base}/leads/{lead['id']}/communications", json={
            "direction": "OUTBOUND", "channel": "CALL", "occurred_at": "2026-02-01T10:00:00Z",
            "notes": "Smoke test call notes.",
        })
        check("communication with notes logged", r.status_code == 201, f"-> {r.status_code} {r.text[:300]}")
        if r.status_code == 201:
            check("notes persisted", r.json().get("notes") == "Smoke test call notes.", f"got {r.json().get('notes')!r}")

    print("\ncleaning up...")
    for lid in cleanup["leads"]:
        dr = c.delete(f"{base}/leads/{lid}")
        print(f"  delete lead {lid}: {dr.status_code}")
    for aid in cleanup["accounts"]:
        dr = c.delete(f"{base}/accounts/{aid}")
        print(f"  delete account {aid}: {dr.status_code}")
    for eid in cleanup["employees"]:
        dr = c.patch(f"{base}/admin/employees/{eid}", json={"is_active": False})
        print(f"  deactivate employee {eid}: {dr.status_code}")

print("\n" + ("ALL CHECKS PASSED" if not failures else f"FAILURES: {failures}"))
