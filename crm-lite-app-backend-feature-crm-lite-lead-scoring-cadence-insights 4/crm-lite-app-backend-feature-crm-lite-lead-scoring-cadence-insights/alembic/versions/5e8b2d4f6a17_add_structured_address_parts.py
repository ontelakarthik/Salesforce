"""add structured address parts (city, postal code) to account and lead

Revision ID: 5e8b2d4f6a17
Revises: 4d2a7e9c1b56
Create Date: 2026-10-06 00:00:00.000000

The existing free-text `account.address` / `account.shipping_address` /
`lead.address` columns are reused as the Billing Street / Shipping Street /
Street, so only the missing parts are added. Purely additive and nullable —
existing rows are untouched.
"""
from alembic import op
import sqlalchemy as sa


revision = '5e8b2d4f6a17'
down_revision = '4d2a7e9c1b56'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('account', sa.Column('billing_city', sa.String(length=100), nullable=True))
    op.add_column('account', sa.Column('billing_postal_code', sa.String(length=20), nullable=True))
    op.add_column('account', sa.Column('shipping_city', sa.String(length=100), nullable=True))
    op.add_column('account', sa.Column('shipping_postal_code', sa.String(length=20), nullable=True))
    op.add_column('lead', sa.Column('city', sa.String(length=100), nullable=True))
    op.add_column('lead', sa.Column('postal_code', sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column('lead', 'postal_code')
    op.drop_column('lead', 'city')
    op.drop_column('account', 'shipping_postal_code')
    op.drop_column('account', 'shipping_city')
    op.drop_column('account', 'billing_postal_code')
    op.drop_column('account', 'billing_city')
