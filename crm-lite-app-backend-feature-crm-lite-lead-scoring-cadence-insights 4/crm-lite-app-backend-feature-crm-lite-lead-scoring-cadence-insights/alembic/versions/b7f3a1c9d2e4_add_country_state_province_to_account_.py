"""add country/state_province to account (billing+shipping) and lead

Revision ID: b7f3a1c9d2e4
Revises: adfafd4cdd6c
Create Date: 2026-09-08 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'b7f3a1c9d2e4'
down_revision = 'adfafd4cdd6c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('account', sa.Column('billing_country', sa.String(length=60), nullable=True))
    op.add_column('account', sa.Column('billing_state_province', sa.String(length=60), nullable=True))
    op.add_column('account', sa.Column('shipping_country', sa.String(length=60), nullable=True))
    op.add_column('account', sa.Column('shipping_state_province', sa.String(length=60), nullable=True))
    op.add_column('lead', sa.Column('country', sa.String(length=60), nullable=True))
    op.add_column('lead', sa.Column('state_province', sa.String(length=60), nullable=True))


def downgrade() -> None:
    op.drop_column('lead', 'state_province')
    op.drop_column('lead', 'country')
    op.drop_column('account', 'shipping_state_province')
    op.drop_column('account', 'shipping_country')
    op.drop_column('account', 'billing_state_province')
    op.drop_column('account', 'billing_country')
