"""add account_id to lead

Revision ID: c9a1e5f7b3d6
Revises: b7f3a1c9d2e4
Create Date: 2026-09-08 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'c9a1e5f7b3d6'
down_revision = 'b7f3a1c9d2e4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('lead', sa.Column('account_id', sa.String(length=20), nullable=True))
    op.create_foreign_key('fk_lead_account_id', 'lead', 'account', ['account_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_lead_account_id', 'lead', type_='foreignkey')
    op.drop_column('lead', 'account_id')
