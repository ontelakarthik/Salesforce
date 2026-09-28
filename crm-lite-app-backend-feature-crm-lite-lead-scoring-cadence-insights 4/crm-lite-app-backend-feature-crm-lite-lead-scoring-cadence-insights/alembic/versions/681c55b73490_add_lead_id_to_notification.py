"""add lead_id to notification

Lets a Notification link back to a Lead (previously only agreement_id/
account_id existed) — needed so flag_lead_hot() can notify the lead's
owner when leadership flags it HOT from the manager dashboard. Purely
additive/nullable, zero behavior change for every existing notification.

Revision ID: 681c55b73490
Revises: a392b55420a3
Create Date: 2026-08-28 12:32:17.033875
"""
from alembic import op
import sqlalchemy as sa


revision = '681c55b73490'
down_revision = 'a392b55420a3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('notification', sa.Column('lead_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_notification_lead_id_lead', 'notification', 'lead', ['lead_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_notification_lead_id_lead', 'notification', type_='foreignkey')
    op.drop_column('notification', 'lead_id')
