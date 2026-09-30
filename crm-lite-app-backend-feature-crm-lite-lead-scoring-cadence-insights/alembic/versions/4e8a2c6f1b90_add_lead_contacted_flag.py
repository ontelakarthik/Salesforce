"""add lead contacted flag

Revision ID: 4e8a2c6f1b90
Revises: 3c9f1e5a7b43
Create Date: 2026-09-30 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '4e8a2c6f1b90'
down_revision = '3c9f1e5a7b43'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('lead', sa.Column('contacted', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    # A lead already past the pre-contact stages has, by definition, had its
    # first contact — backfill those so a later Email/SMS/Call can never
    # auto-revert them to CONTACTED. NEW/ATTEMPTING_CONTACT stay false.
    op.execute(
        "UPDATE lead SET contacted = true "
        "WHERE status NOT IN ('NEW', 'ATTEMPTING_CONTACT')"
    )


def downgrade() -> None:
    op.drop_column('lead', 'contacted')
