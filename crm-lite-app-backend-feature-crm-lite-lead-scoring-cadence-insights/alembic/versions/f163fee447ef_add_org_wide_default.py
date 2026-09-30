"""add org wide default

Adds the per-object row-visibility baseline (LEAD/ACCOUNT/OPPORTUNITY),
seeded PRIVATE for all three — PRIVATE reproduces today's ownership/role-
hierarchy/records.see_all scoping behavior exactly, so this ships as a
zero-behavior-change migration until an admin changes a setting via
PUT /admin/org-wide-defaults.

Also grants ADMIN the new org_wide_defaults.write capability (same pattern as
a04a019aaaf4_add_object_crud_capabilities.py's ADMIN-only accounts.delete
grant) — a raw data migration doesn't go through save_profile_capabilities()'s
"ADMIN must keep every capability" check, so this is the one place that
invariant has to be maintained by hand for a brand-new key.

Revision ID: f163fee447ef
Revises: fb2e5174c29e
Create Date: 2026-09-07 00:00:00.000000
"""
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'f163fee447ef'
down_revision = 'fb2e5174c29e'
branch_labels = None
depends_on = None

CAPABILITY_KEY = 'org_wide_defaults.write'


def upgrade() -> None:
    op.create_table('org_wide_default',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('object_name', sa.String(length=20), nullable=False),
    sa.Column('access_level', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=True),
    sa.Column('updated_by', sa.String(length=64), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('object_name')
    )

    org_wide_default = sa.table(
        'org_wide_default',
        sa.column('object_name', sa.String),
        sa.column('access_level', sa.String),
    )
    op.bulk_insert(org_wide_default, [
        {'object_name': 'LEAD', 'access_level': 'PRIVATE'},
        {'object_name': 'ACCOUNT', 'access_level': 'PRIVATE'},
        {'object_name': 'OPPORTUNITY', 'access_level': 'PRIVATE'},
    ])

    conn = op.get_bind()
    admin_role = conn.execute(sa.text("SELECT id FROM role WHERE code = 'ADMIN'")).fetchone()
    if admin_role is not None:
        already_granted = conn.execute(sa.text(
            "SELECT 1 FROM role_capability WHERE role_id = :rid AND capability_key = :key "
            "AND deleted_at IS NULL"
        ), {"rid": admin_role[0], "key": CAPABILITY_KEY}).fetchone()
        if already_granted is None:
            role_capability = sa.table(
                "role_capability",
                sa.column("id", postgresql.UUID(as_uuid=True)),
                sa.column("role_id", sa.Integer),
                sa.column("capability_key", sa.String),
                sa.column("created_at", sa.DateTime(timezone=True)),
                sa.column("updated_at", sa.DateTime(timezone=True)),
            )
            now = datetime.now(timezone.utc)
            op.bulk_insert(role_capability, [{
                "id": uuid.uuid4(), "role_id": admin_role[0], "capability_key": CAPABILITY_KEY,
                "created_at": now, "updated_at": now,
            }])


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text(
        "DELETE FROM role_capability WHERE capability_key = :key"), {"key": CAPABILITY_KEY})
    op.drop_table('org_wide_default')
