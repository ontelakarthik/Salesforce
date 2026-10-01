"""One-off diagnostic: exercise the live Territory Management feature
(hierarchy, id-based Employee assignment, Account/Lead territory-by-Name
display) against the deployed backend, exactly like a real browser session
would. Mints the token in-process (never prints the JWT secret), creates
real rows over HTTPS, confirms persistence via re-fetch, and cleans up
everything it created.
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
cleanup = {"territories": [], "employees": [], "accounts": [], "leads": []}


def check(label, condition, detail=""):
    status = "OK" if condition else "FAIL"
    print(f"[{status}] {label} {detail}")
    if not condition:
        failures.append(label)


with httpx.Client(headers=headers, timeout=30) as c:
    # --- Seeded USA/Canada hierarchy ---
    rows = c.get(f"{base}/admin/lookups/territory").json()
    by_name = {r["display_name"]: r for r in rows}
    usa = next((r for r in rows if r["code"] == "USA"), None)
    canada = next((r for r in rows if r["code"] == "CANADA"), None)
    check("USA top-level territory seeded", usa is not None)
    check("Canada top-level territory seeded", canada is not None)
    if usa:
        check("USA has no region (country-wide)", usa["region"] is None)
    for name, region in [("USA - Northeast", "Northeast"), ("USA - West", "West")]:
        row = by_name.get(name)
        check(f"{name} seeded under USA", row is not None and row["parent_territory_id"] == (usa or {}).get("id"),
              f"got {row}")
        if row:
            check(f"{name} region correct", row["region"] == region)
    for name, region in [("Canada - Atlantic", "Atlantic"), ("Canada - Central", "Central Canada")]:
        row = by_name.get(name)
        check(f"{name} seeded under Canada", row is not None and row["parent_territory_id"] == (canada or {}).get("id"),
              f"got {row}")
        if row:
            check(f"{name} region correct", row["region"] == region)

    # --- Create a territory without code, with a parent, region optional ---
    r = c.post(f"{base}/admin/lookups/territory", json={
        "display_name": "Smoke Test Territory (No Code)", "country": "USA",
        "parent_territory_id": usa["id"] if usa else None, "is_active": True,
    })
    check("create territory without code", r.status_code == 201, f"-> {r.status_code} {r.text[:300]}")
    no_code_territory = r.json() if r.status_code == 201 else None
    if no_code_territory:
        cleanup["territories"].append(no_code_territory["id"])
        check("code is null", no_code_territory["code"] is None)
        check("region is null (optional, not given)", no_code_territory["region"] is None)

    # --- Cycle detection ---
    if no_code_territory:
        r = c.patch(f"{base}/admin/lookups/territory/{no_code_territory['id']}",
                   json={"parent_territory_id": no_code_territory["id"]})
        check("self-parent rejected", r.status_code == 422, f"-> {r.status_code}")

    # --- Employee assignment by territory_id, code-optional territory selectable ---
    if no_code_territory:
        r = c.post(f"{base}/admin/employees", json={
            "email": f"smoke.terr.mgmt.{uuid.uuid4().hex[:8]}@example.invalid",
            "full_name": "Smoke Territory Mgmt Rep", "territory_id": no_code_territory["id"],
        })
        check("employee assigned to code-less territory", r.status_code == 201, f"-> {r.status_code} {r.text[:300]}")
        rep = r.json() if r.status_code == 201 else None
        if rep:
            cleanup["employees"].append(rep["id"])
            check("territory_id stored", rep["territory_id"] == no_code_territory["id"])
            check("territory_name resolved", rep["territory_name"] == "Smoke Test Territory (No Code)")

            # Re-fetch (edit-employee load path) confirms persistence.
            listed = c.get(f"{base}/admin/employees").json()
            row = next(e for e in listed if e["id"] == rep["id"])
            check("territory persists on re-fetch", row["territory_id"] == no_code_territory["id"])

            # --- Account/Lead territory display resolves to Name via territory_id ---
            r = c.post(f"{base}/accounts", json={
                "legal_name": "Smoke Territory Mgmt Account", "owner_employee_id": rep["id"],
            })
            check("account created with owner", r.status_code == 201, f"-> {r.status_code} {r.text[:300]}")
            if r.status_code == 201:
                account = r.json()
                cleanup["accounts"].append(account["id"])
                check("account territory shows Name, not id/code",
                      account["territory"] == "Smoke Test Territory (No Code)", f"got {account['territory']!r}")

            r = c.post(f"{base}/leads", json={
                "company_name": "Smoke Territory Mgmt Lead", "last_name": "Doe",
                "contact_email": "smoke.lead.terrmgmt@example.invalid", "owner_employee_id": rep["id"],
            })
            check("lead created with owner", r.status_code == 201, f"-> {r.status_code} {r.text[:300]}")
            if r.status_code == 201:
                lead = r.json()
                cleanup["leads"].append(lead["id"])
                check("lead territory shows Name, not id/code",
                      lead["territory"] == "Smoke Test Territory (No Code)", f"got {lead['territory']!r}")

    # --- Inactive territory cannot be newly assigned ---
    r = c.post(f"{base}/admin/lookups/territory", json={
        "display_name": "Smoke Inactive Territory", "country": "USA", "is_active": False,
    })
    inactive_territory = r.json() if r.status_code == 201 else None
    if inactive_territory:
        cleanup["territories"].append(inactive_territory["id"])
        r = c.post(f"{base}/admin/employees", json={
            "email": f"smoke.inactive.{uuid.uuid4().hex[:8]}@example.invalid",
            "full_name": "Smoke Inactive Assignee", "territory_id": inactive_territory["id"],
        })
        check("inactive territory rejected for new assignment", r.status_code == 422, f"-> {r.status_code}")

    print("\ncleaning up...")
    for lid in cleanup["leads"]:
        print(f"  delete lead {lid}: {c.delete(f'{base}/leads/{lid}').status_code}")
    for aid in cleanup["accounts"]:
        print(f"  delete account {aid}: {c.delete(f'{base}/accounts/{aid}').status_code}")
    for eid in cleanup["employees"]:
        print(f"  deactivate employee {eid}: {c.patch(f'{base}/admin/employees/{eid}', json={'is_active': False}).status_code}")
    for tid in cleanup["territories"]:
        print(f"  deactivate territory {tid}: {c.patch(f'{base}/admin/lookups/territory/{tid}', json={'is_active': False}).status_code}")

print("\n" + ("ALL CHECKS PASSED" if not failures else f"FAILURES: {failures}"))
