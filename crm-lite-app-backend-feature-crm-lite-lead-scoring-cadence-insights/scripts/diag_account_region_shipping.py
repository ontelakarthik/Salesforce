"""One-off diagnostic: exercise the live Account Region derivation and
Billing->Shipping auto-copy behavior against the deployed backend, exactly
like a real browser session would. Mints the token in-process (never prints
the JWT secret), creates/updates real Account rows over HTTPS, re-fetches
them to confirm persistence (not just the in-request response), then
cleans up the accounts it created.
"""
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

created_ids = []
failures = []


def check(label, condition, detail=""):
    status = "OK" if condition else "FAIL"
    print(f"[{status}] {label} {detail}")
    if not condition:
        failures.append(label)


with httpx.Client(headers=headers, timeout=30) as c:
    # --- Case 1: Region derives from billing country+state; shipping copies from billing ---
    r = c.post(f"{base}/accounts", json={
        "legal_name": "Smoke Test Region CA",
        "billing_country": "USA",
        "billing_state_province": "California",
        "address": "1600 Amphitheatre Parkway, Mountain View, CA 94043, USA",
    })
    check("create account (USA/California)", r.status_code == 201, f"-> {r.status_code} {r.text[:300]}")
    if r.status_code == 201:
        acc = r.json()
        created_ids.append(acc["id"])
        check("region derived as West", acc.get("region") == "West", f"got {acc.get('region')!r}")
        check("shipping_address copied from billing", acc.get("shipping_address") == acc.get("address"), f"got {acc.get('shipping_address')!r}")
        check("shipping_country copied", acc.get("shipping_country") == "USA", f"got {acc.get('shipping_country')!r}")
        check("shipping_state_province copied", acc.get("shipping_state_province") == "California", f"got {acc.get('shipping_state_province')!r}")

        # Re-fetch to confirm real persistence, not just the create response
        r2 = c.get(f"{base}/accounts/{acc['id']}")
        acc2 = r2.json()
        check("region persists after refresh", acc2.get("region") == "West", f"got {acc2.get('region')!r}")
        check("shipping persists after refresh", acc2.get("shipping_address") == acc.get("address"), f"got {acc2.get('shipping_address')!r}")

    # --- Case 2: explicit shipping address is preserved, not overwritten ---
    r = c.post(f"{base}/accounts", json={
        "legal_name": "Smoke Test Explicit Shipping",
        "billing_country": "USA",
        "billing_state_province": "Texas",
        "address": "100 Billing St, Austin, TX, USA",
        "shipping_address": "200 Shipping Ave, Dallas, TX, USA",
    })
    check("create account (explicit shipping)", r.status_code == 201, f"-> {r.status_code} {r.text[:300]}")
    if r.status_code == 201:
        acc = r.json()
        created_ids.append(acc["id"])
        check("region derived as South", acc.get("region") == "South", f"got {acc.get('region')!r}")
        check("explicit shipping_address preserved", acc.get("shipping_address") == "200 Shipping Ave, Dallas, TX, USA", f"got {acc.get('shipping_address')!r}")

    # --- Case 3: Canada region mapping (Ontario -> Central Canada) ---
    r = c.post(f"{base}/accounts", json={
        "legal_name": "Smoke Test Region Canada",
        "billing_country": "Canada",
        "billing_state_province": "Ontario",
        "address": "1 Yonge St, Toronto, ON, Canada",
    })
    check("create account (Canada/Ontario)", r.status_code == 201, f"-> {r.status_code} {r.text[:300]}")
    if r.status_code == 201:
        acc = r.json()
        created_ids.append(acc["id"])
        check("region derived as Central Canada", acc.get("region") == "Central Canada", f"got {acc.get('region')!r}")

    # --- Case 4: no billing country/state -> region null, no shipping copy ---
    r = c.post(f"{base}/accounts", json={"legal_name": "Smoke Test No Geo"})
    check("create account (no geo)", r.status_code == 201, f"-> {r.status_code} {r.text[:300]}")
    if r.status_code == 201:
        acc = r.json()
        created_ids.append(acc["id"])
        check("region is null", acc.get("region") is None, f"got {acc.get('region')!r}")
        check("shipping_address stays empty", not acc.get("shipping_address"), f"got {acc.get('shipping_address')!r}")

    # --- Case 5: update path - billing added later on an existing account with no shipping ---
    r = c.post(f"{base}/accounts", json={"legal_name": "Smoke Test Update Path"})
    if r.status_code == 201:
        acc = r.json()
        created_ids.append(acc["id"])
        r = c.patch(f"{base}/accounts/{acc['id']}", json={
            "billing_country": "USA",
            "billing_state_province": "New York",
            "address": "1 Wall St, New York, NY, USA",
        })
        check("update account with billing", r.status_code == 200, f"-> {r.status_code} {r.text[:300]}")
        if r.status_code == 200:
            acc2 = r.json()
            check("region derived as Northeast on update", acc2.get("region") == "Northeast", f"got {acc2.get('region')!r}")
            check("shipping copied on update", acc2.get("shipping_address") == acc2.get("address"), f"got {acc2.get('shipping_address')!r}")
            r3 = c.get(f"{base}/accounts/{acc['id']}")
            acc3 = r3.json()
            check("update-path shipping persists after refresh", acc3.get("shipping_address") == acc2.get("address"), f"got {acc3.get('shipping_address')!r}")

    # cleanup
    print("\ncleaning up", len(created_ids), "test accounts...")
    for aid in created_ids:
        dr = c.delete(f"{base}/accounts/{aid}")
        print(f"  delete {aid}: {dr.status_code}")

print("\n" + ("ALL CHECKS PASSED" if not failures else f"FAILURES: {failures}"))
