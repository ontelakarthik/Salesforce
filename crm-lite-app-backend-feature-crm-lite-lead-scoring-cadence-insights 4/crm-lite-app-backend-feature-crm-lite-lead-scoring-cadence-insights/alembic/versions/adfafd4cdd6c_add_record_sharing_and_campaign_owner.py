"""add record sharing, campaign owner, and CONTACT/CAMPAIGN OWD rows

Salesforce-style OWD + record ownership + Role Hierarchy + user-based
Sharing Rules for Lead/Account/Contact/Opportunity/Campaign (see
services/record_access_service.py). Additive only, and every seed choice
below is picked so nothing currently visible becomes invisible:

- campaign.owner_employee_id (nullable FK -> employee.id) -- Campaign
  previously had no owner and no scope check at all.
- record_share table -- one row per (object, record, employee) grant,
  access_level READ|EDIT only (never DELETE).
- 2 new org_wide_default rows: CONTACT seeded PRIVATE, CAMPAIGN seeded
  PUBLIC_READ_WRITE. CONTACT's PRIVATE reproduces its effective behavior
  today exactly -- Contact access has always been 100% inherited from its
  parent Account's owner, and record_access_service.py's Role Hierarchy
  path (a manager still reaches a subordinate-owned Account's contacts)
  covers the rest. CAMPAIGN gets PUBLIC_READ_WRITE specifically because it
  never had an owner or Role Hierarchy concept to fall back on -- every
  existing (currently unowned) campaign needs to stay visible AND editable
  to anyone with platform.read/campaigns.write exactly as before; PRIVATE
  would have made every pre-existing campaign invisible to non-admins the
  moment this migration ran. An admin can tighten CAMPAIGN's OWD later via
  PUT /org-wide-defaults if per-campaign scoping is ever wanted.
- grants the new record_shares.write capability to every role currently
  holding leads.write (SALES/ACCOUNT_EXEC/LEADERSHIP/ADMIN in the original
  seed -- sharing an individual record you can already edit is a day-to-day
  working action, not global config, so it's seeded at that tier rather than
  ADMIN-only like org_wide_defaults.write), plus unconditionally to ADMIN
  (same "a raw data migration doesn't go through save_profile_capabilities()'s
  ADMIN-must-keep-every-capability check" reasoning as f163fee447ef).

Does NOT modify d48740d826f1_add_lead_scoring_and_sales_cadence.py or any
other existing migration.

Revision ID: adfafd4cdd6c
Revises: 0e60621733d4
Create Date: 2026-09-07 00:00:00.000000
"""
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = 'adfafd4cdd6c'
down_revision = '0e60621733d4'
branch_labels = None
depends_on = None

CAPABILITY_KEY = 'record_shares.write'
TRIGGER_CAPABILITY_KEY = 'leads.write'


def upgrade() -> None:
    # --- Campaign owner -----------------------------------------------------
    op.add_column('campaign', sa.Column('owner_employee_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_campaign_owner_employee_id', 'campaign', 'employee',
        ['owner_employee_id'], ['id'])

    # --- record_share --------------------------------------------------------
    op.create_table('record_share',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('object_name', sa.String(length=20), nullable=False),
    sa.Column('record_id', sa.String(length=40), nullable=False),
    sa.Column('shared_with_employee_id', sa.UUID(), nullable=False),
    sa.Column('access_level', sa.String(length=10), nullable=False),
    sa.Column('granted_by', sa.UUID(), nullable=True),
    sa.Column('granted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=True),
    sa.Column('updated_by', sa.String(length=64), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['shared_with_employee_id'], ['employee.id']),
    sa.ForeignKeyConstraint(['granted_by'], ['employee.id']),
    sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_record_share_object_record_employee', 'record_share',
        ['object_name', 'record_id', 'shared_with_employee_id'],
        unique=True, postgresql_where=sa.text('deleted_at IS NULL'),
    )
    op.create_index(
        'ix_record_share_object_record', 'record_share', ['object_name', 'record_id'])

    # --- CONTACT/CAMPAIGN OWD rows -------------------------------------------
    org_wide_default = sa.table(
        'org_wide_default',
        sa.column('object_name', sa.String),
        sa.column('access_level', sa.String),
    )
    op.bulk_insert(org_wide_default, [
        {'object_name': 'CONTACT', 'access_level': 'PRIVATE'},
        {'object_name': 'CAMPAIGN', 'access_level': 'PUBLIC_READ_WRITE'},
    ])

    # --- record_shares.write capability grant --------------------------------
    conn = op.get_bind()
    trigger_role_ids = {row[0] for row in conn.execute(sa.text(
        "SELECT role_id FROM role_capability WHERE capability_key = :key AND deleted_at IS NULL"
    ), {"key": TRIGGER_CAPABILITY_KEY}).fetchall()}
    admin_role = conn.execute(sa.text("SELECT id FROM role WHERE code = 'ADMIN'")).fetchone()
    if admin_role is not None:
        trigger_role_ids.add(admin_role[0])

    already_granted = {row[0] for row in conn.execute(sa.text(
        "SELECT role_id FROM role_capability WHERE capability_key = :key AND deleted_at IS NULL"
    ), {"key": CAPABILITY_KEY}).fetchall()}

    role_capability = sa.table(
        "role_capability",
        sa.column("id", sa.UUID),
        sa.column("role_id", sa.Integer),
        sa.column("capability_key", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(timezone.utc)
    new_rows = [
        {"id": uuid.uuid4(), "role_id": role_id, "capability_key": CAPABILITY_KEY,
         "created_at": now, "updated_at": now}
        for role_id in trigger_role_ids - already_granted
    ]
    if new_rows:
        op.bulk_insert(role_capability, new_rows)


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text(
        "DELETE FROM role_capability WHERE capability_key = :key"), {"key": CAPABILITY_KEY})
    conn.execute(sa.text(
        "DELETE FROM org_wide_default WHERE object_name IN ('CONTACT', 'CAMPAIGN')"))
    op.drop_index('ix_record_share_object_record', table_name='record_share')
    op.drop_index('ix_record_share_object_record_employee', table_name='record_share')
    op.drop_table('record_share')
    op.drop_constraint('fk_campaign_owner_employee_id', 'campaign', type_='foreignkey')
    op.drop_column('campaign', 'owner_employee_id')
