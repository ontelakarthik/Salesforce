"""add profile capabilities

Adds admin-configurable object-level access ("Profiles"): a new `is_system`
column on `role` (protects the 4 originally-seeded rows from delete/rename)
and a new `role_capability` table (which capability keys — see
utils.permissions.CAPABILITY_REGISTRY — each role/profile is granted).

The seed data below reproduces the OLD static CAPABILITIES dict from
utils/permissions.py exactly, for the 4 originally-seeded roles, plus two
new capabilities (records.see_all/audit.see_all) that formalize what used
to be three independently-copy-pasted role tuples scattered across the
service layer. This is a hard regression guarantee, not a behavior change.

Schema + seed ship in this ONE migration deliberately — not split across
two — because the moment new backend code starts reading role_capability,
an empty table means every capability check fails default-deny, including
ADMIN. This migration must finish running (schema + seed together) before
the new backend revision that reads it is deployed.

Revision ID: f469eb05be31
Revises: ba30464cb885
Create Date: 2026-08-27 13:45:00.000000
"""
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'f469eb05be31'
down_revision = 'ba30464cb885'
branch_labels = None
depends_on = None

# Reproduces utils/permissions.py's old CAPABILITIES dict one-for-one, plus
# records.see_all (replaces the three copy-pasted _ALL_SCOPE_ROLES tuples in
# crm_service.py/platform_service.py/scope.py) and audit.see_all (replaces
# activity_service.py's narrower _SEES_ALL_AUDIT_ROLES).
CAPABILITY_ROLE_CODES: dict[str, list[str]] = {
    "platform.read": ["SALES", "ACCOUNT_EXEC", "LEADERSHIP", "ADMIN"],
    "campaigns.write": ["SALES", "ACCOUNT_EXEC", "ADMIN"],
    "leads.write": ["SALES", "ACCOUNT_EXEC", "ADMIN"],
    "leads.convert": ["SALES", "ACCOUNT_EXEC", "ADMIN"],
    "leads.flag_hot": ["LEADERSHIP", "ADMIN"],
    "lead_scoring_rules.write": ["ADMIN"],
    "cadence_templates.write": ["ADMIN"],
    "field_permissions.write": ["ADMIN"],
    "products.write": ["ADMIN"],
    "cadences.enroll": ["SALES", "ACCOUNT_EXEC", "ADMIN"],
    "manager_dashboard.read": ["ACCOUNT_EXEC", "LEADERSHIP", "ADMIN"],
    "accounts.write": ["SALES", "ACCOUNT_EXEC", "ADMIN"],
    "accounts.promote": ["SALES", "ACCOUNT_EXEC", "ADMIN"],
    "accounts.assign": ["ACCOUNT_EXEC", "ADMIN"],
    "opportunities.write": ["SALES", "ACCOUNT_EXEC", "ADMIN"],
    "projects.write": ["ACCOUNT_EXEC", "ADMIN"],
    "agreements.write": ["ACCOUNT_EXEC", "ADMIN"],
    "agreements.sign": ["ACCOUNT_EXEC", "LEADERSHIP", "ADMIN"],
    "sow.write": ["ACCOUNT_EXEC", "ADMIN"],
    "timesheets.read": ["SALES", "ACCOUNT_EXEC", "ADMIN"],
    "timesheets.submit": ["SALES", "ACCOUNT_EXEC", "ADMIN"],
    "timesheets.approve": ["ACCOUNT_EXEC", "ADMIN"],
    "audit.read": ["ACCOUNT_EXEC", "LEADERSHIP", "ADMIN"],
    "admin": ["ADMIN"],
    "records.see_all": ["ACCOUNT_EXEC", "LEADERSHIP", "ADMIN"],
    "audit.see_all": ["LEADERSHIP", "ADMIN"],
}


def upgrade() -> None:
    op.add_column('role', sa.Column('is_system', sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table('role_capability',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('role_id', sa.Integer(), nullable=False),
    sa.Column('capability_key', sa.String(length=60), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=True),
    sa.Column('updated_by', sa.String(length=64), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['role_id'], ['role.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_role_capability_role_key', 'role_capability', ['role_id', 'capability_key'],
                     unique=True, postgresql_where=sa.text('deleted_at IS NULL'))

    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE role SET is_system = TRUE WHERE code IN ('SALES','ACCOUNT_EXEC','LEADERSHIP','ADMIN')"))

    role_ids = dict(conn.execute(sa.text("SELECT code, id FROM role")).fetchall())

    role_capability = sa.table(
        "role_capability",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("role_id", sa.Integer),
        sa.column("capability_key", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(timezone.utc)
    seed_rows = [
        {"id": uuid.uuid4(), "role_id": role_ids[code], "capability_key": key,
         "created_at": now, "updated_at": now}
        for key, codes in CAPABILITY_ROLE_CODES.items()
        for code in codes
        if code in role_ids
    ]
    if seed_rows:
        op.bulk_insert(role_capability, seed_rows)


def downgrade() -> None:
    op.drop_index('ix_role_capability_role_key', table_name='role_capability',
                  postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_table('role_capability')
    op.drop_column('role', 'is_system')
