"""add object CRUD capabilities

Reseeds role_capability so every existing profile (all 4 system ones, and
any custom profile an admin already created) keeps identical effective
access once crm_routes.py switches Lead/Account/Opportunity CRUD from the
bundled X.write/platform.read keys to fine-grained X.create/X.edit/X.delete/
X.read (see utils/permissions.py's updated docstring):

- Holding X.write today -> also granted X.create + X.edit (+ X.delete for
  Lead/Opportunity; Account delete was never part of accounts.write, see
  below).
- Holding platform.read today -> also granted leads.read/accounts.read/
  opportunities.read (platform.read itself is untouched everywhere else).
- ADMIN explicitly granted accounts.delete: DELETE /accounts/{id} used to be
  gated by the bare `admin` key, not accounts.write, so nothing above
  implies it -- this migration is the one place ADMIN's full-capability
  invariant has to be maintained by hand, since a raw data migration doesn't
  go through save_profile_capabilities()'s "ADMIN must keep every
  capability" check.

Also revokes ACCOUNT_EXEC's manager_dashboard.read (part of the dashboard
split -- AE now sees the personal rep dashboard, not the manager one; an
admin can re-grant it per-profile via /admin/profiles if they ever want an
AE to see the manager view).

Purely additive/data-only -- no schema change. Ships as one migration since
both changes are plain INSERT/DELETE with no ordering hazard between them.

Revision ID: a04a019aaaf4
Revises: 681c55b73490
Create Date: 2026-08-28 13:05:00.000000
"""
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'a04a019aaaf4'
down_revision = '681c55b73490'
branch_labels = None
depends_on = None

IMPLICATIONS = {
    "leads.write": ("leads.create", "leads.edit", "leads.delete"),
    "accounts.write": ("accounts.create", "accounts.edit"),
    "opportunities.write": ("opportunities.create", "opportunities.edit", "opportunities.delete"),
    "platform.read": ("leads.read", "accounts.read", "opportunities.read"),
}

NEW_KEYS = (
    "leads.create", "leads.edit", "leads.delete", "leads.read",
    "accounts.create", "accounts.edit", "accounts.delete", "accounts.read",
    "opportunities.create", "opportunities.edit", "opportunities.delete", "opportunities.read",
)


def upgrade() -> None:
    conn = op.get_bind()
    granted = conn.execute(sa.text(
        "SELECT role_id, capability_key FROM role_capability WHERE deleted_at IS NULL")).fetchall()
    granted_set = {(row[0], row[1]) for row in granted}

    role_capability = sa.table(
        "role_capability",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("role_id", sa.Integer),
        sa.column("capability_key", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(timezone.utc)
    new_rows = []
    seen_new: set[tuple[int, str]] = set()

    def add(role_id: int, key: str) -> None:
        pair = (role_id, key)
        if pair in granted_set or pair in seen_new:
            return
        seen_new.add(pair)
        new_rows.append({"id": uuid.uuid4(), "role_id": role_id, "capability_key": key,
                         "created_at": now, "updated_at": now})

    for role_id, old_key in granted_set:
        for new_key in IMPLICATIONS.get(old_key, ()):
            add(role_id, new_key)

    admin_role = conn.execute(sa.text("SELECT id FROM role WHERE code = 'ADMIN'")).fetchone()
    if admin_role is not None:
        add(admin_role[0], "accounts.delete")

    if new_rows:
        op.bulk_insert(role_capability, new_rows)

    ae_role = conn.execute(sa.text("SELECT id FROM role WHERE code = 'ACCOUNT_EXEC'")).fetchone()
    if ae_role is not None:
        conn.execute(sa.text(
            "DELETE FROM role_capability WHERE role_id = :rid AND capability_key = 'manager_dashboard.read'"
        ), {"rid": ae_role[0]})


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text(
        "DELETE FROM role_capability WHERE capability_key = ANY(:keys)"
    ), {"keys": list(NEW_KEYS)})

    ae_role = conn.execute(sa.text("SELECT id FROM role WHERE code = 'ACCOUNT_EXEC'")).fetchone()
    if ae_role is not None:
        exists = conn.execute(sa.text(
            "SELECT 1 FROM role_capability WHERE role_id = :rid AND capability_key = 'manager_dashboard.read'"
        ), {"rid": ae_role[0]}).fetchone()
        if exists is None:
            conn.execute(sa.text(
                "INSERT INTO role_capability (id, role_id, capability_key, created_at, updated_at) "
                "VALUES (:id, :rid, 'manager_dashboard.read', now(), now())"
            ), {"id": str(uuid.uuid4()), "rid": ae_role[0]})
