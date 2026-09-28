"""One-off diagnostic: call the live GET /leads endpoint as the real admin
user to see the exact status/body a real browser session would get. Mints
the token in-process (never prints the JWT secret) and hits the backend's
own public URL over HTTPS, exactly like the frontend does."""
import httpx

from src.repositories.admin_repository import get_employee_repository
from src.services.auth_service import _role_codes_for_employee, mint_token_for_profiles

emp = get_employee_repository().find_by_email("vikram.tagirisepu@tachyontech.com")
if emp is None:
    print("admin employee not found")
    raise SystemExit(0)

role_codes = _role_codes_for_employee(emp.id)
token = mint_token_for_profiles(str(emp.id), set(role_codes))

url = "https://crm-lite-backend-819750641834.asia-south1.run.app/api/v1/leads"
resp = httpx.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
print("status:", resp.status_code)
print("body (first 2000 chars):", resp.text[:2000])
