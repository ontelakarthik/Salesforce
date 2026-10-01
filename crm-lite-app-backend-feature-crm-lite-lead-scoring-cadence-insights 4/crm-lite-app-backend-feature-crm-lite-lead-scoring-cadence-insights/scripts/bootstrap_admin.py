"""Create the very first ADMIN account in a fresh deployment.

There's a deliberate chicken-and-egg gap in this app: creating an employee
and assigning profiles both require an authenticated ADMIN caller
(POST /admin/employees, PUT /admin/employees/{id}/profiles), but a brand-new
database has no employees at all yet. Locally, DEV_AUTH_BYPASS=true papers
over this (every request is treated as ADMIN). In a real deployment
(DEV_AUTH_BYPASS correctly off — see config.py), nothing can call those
endpoints yet, so this script goes around the API entirely and calls the
same service functions directly, the one time that's appropriate.

Idempotent: re-running for an existing email just (re-)grants ADMIN and
resets the password rather than failing — safe to run again if the first
attempt's email delivery failed, or the account needs recovering.

Run:
    uv run python -m scripts.bootstrap_admin --email you@yourcompany.com --full-name "Your Name"
"""
from __future__ import annotations

import argparse

from src.models import admin_models
from src.repositories.admin_repository import get_employee_repository
from src.services import admin_service
from src.services.email_client import get_optional_email_sender
from src.utils.passwords import generate_temp_password, hash_password
from src.utils.permissions import CAPABILITY_REGISTRY
from src.utils.security import CurrentUser

_BOOTSTRAP_USER = CurrentUser(employee_id="bootstrap-script", profile_codes={"ADMIN"},
                              capabilities=set(CAPABILITY_REGISTRY.keys()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--full-name", required=True)
    args = parser.parse_args()

    email = args.email.strip().lower()
    emp_repo = get_employee_repository()
    existing = emp_repo.find_by_email(email)

    if existing is None:
        created = admin_service.create_employee(
            _BOOTSTRAP_USER, get_optional_email_sender(),
            admin_models.EmployeeCreate(email=email, full_name=args.full_name),
        )
        employee_id = created.id
        print(f"Created employee {email} ({employee_id}).")
        if created.password_email_sent:
            print("A welcome email with a temporary password was sent to them.")
        else:
            print("Email isn't configured here — no welcome email was sent.")
            print("Re-run this script after configuring SMTP, or set a password by hand below.")
    else:
        employee_id = existing.id
        temp_password = generate_temp_password()
        emp_repo.update(employee_id, password_hash=hash_password(temp_password),
                        must_change_password=True, is_active=True, updated_by="bootstrap-script")
        print(f"{email} already existed ({employee_id}) — reset their password.")
        print(f"Temporary password: {temp_password}")

    admin_service.set_employee_profiles(
        _BOOTSTRAP_USER, employee_id, admin_models.EmployeeProfilesUpdate(profile_codes=["ADMIN"]))
    print(f"Granted ADMIN to {email}. They can now sign in at /login.")


if __name__ == "__main__":
    main()
