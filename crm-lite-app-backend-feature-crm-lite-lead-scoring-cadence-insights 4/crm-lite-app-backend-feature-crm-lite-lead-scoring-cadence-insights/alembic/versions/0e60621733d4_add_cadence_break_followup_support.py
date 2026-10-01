"""add cadence break/follow-up support (skip_weekends, auto_resolved)

Revision ID: 0e60621733d4
Revises: f163fee447ef
Create Date: 2026-09-07 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0e60621733d4'
down_revision = 'f163fee447ef'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Additive only — does not touch d48740d826f1_add_lead_scoring_and_sales_cadence.py.
    # Backfill existing rows to the safe default (false) via server_default,
    # then drop it so future ORM inserts must supply the value explicitly —
    # same two-step pattern d48740d826f1 used for lead.lead_score.
    op.add_column('cadence_step',
        sa.Column('skip_weekends', sa.Boolean(), nullable=False, server_default='false'))
    op.alter_column('cadence_step', 'skip_weekends', server_default=None)

    op.add_column('cadence_task',
        sa.Column('auto_resolved', sa.Boolean(), nullable=False, server_default='false'))
    op.alter_column('cadence_task', 'auto_resolved', server_default=None)


def downgrade() -> None:
    op.drop_column('cadence_task', 'auto_resolved')
    op.drop_column('cadence_step', 'skip_weekends')
