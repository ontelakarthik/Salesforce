"""One-off diagnostic: dump an employee's account state and password-change
history without exposing the actual password hash. Run as a Cloud Run Job
against the production image/env — see the backend service's own env vars
for DATABASE_URL etc."""
import sys

from sqlalchemy import select

from src.models.activity_models import AuditLog
from src.repositories.admin_repository import get_employee_repository
from src.services.db_client import get_session_factory

email = sys.argv[1].strip().lower()
repo = get_employee_repository()
emp = repo.find_by_email(email)

if emp is None:
    print(f"No employee found for {email}")
    sys.exit(0)

print(f"id: {emp.id}")
print(f"email: {emp.email}")
print(f"full_name: {emp.full_name}")
print(f"is_active: {emp.is_active}")
print(f"must_change_password: {emp.must_change_password}")
print(f"password_hash prefix: {emp.password_hash[:10] if emp.password_hash else None}")
print(f"password_hash length: {len(emp.password_hash) if emp.password_hash else 0}")
print(f"created_at: {emp.created_at}")
print(f"updated_at: {emp.updated_at}")
print(f"created_by: {emp.created_by}")
print(f"updated_by: {emp.updated_by}")

session_factory = get_session_factory()
with session_factory() as db:
    stmt = (
        select(AuditLog)
        .where(AuditLog.entity_type == "employee", AuditLog.entity_id == str(emp.id))
        .order_by(AuditLog.performed_at)
    )
    rows = db.execute(stmt).scalars().all()

print(f"\naudit trail ({len(rows)} entries):")
for r in rows:
    old = r.old_value[:10] + "..." if r.field_changed == "password_hash" and r.old_value else r.old_value
    new = r.new_value[:10] + "..." if r.field_changed == "password_hash" and r.new_value else r.new_value
    print(f"  {r.performed_at}  {r.action:12s} field={r.field_changed} old={old!r} new={new!r} by={r.performed_by_employee_id}")
