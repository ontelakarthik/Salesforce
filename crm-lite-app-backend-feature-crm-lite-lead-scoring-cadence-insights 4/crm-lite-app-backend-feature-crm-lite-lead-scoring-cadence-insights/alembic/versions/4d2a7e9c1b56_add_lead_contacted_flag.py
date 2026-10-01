"""add lead contacted flag

Revision ID: 4d2a7e9c1b56
Revises: 3c9f1e5a7b43
Create Date: 2026-10-01 00:00:00.000000

Backend-only flag recording whether a Lead has had its first successful
Email/SMS/Call (see activity_service.mark_lead_as_contacted_if_first_contact()).

Existing rows default to false, except leads whose status already says a
real conversation happened (CONTACTED and every stage past it) — by
LeadStatus's own definition those were contacted, so leaving them false
would let their next Email/SMS/Call treat it as a "first" contact.
NEW/ATTEMPTING_CONTACT/UNQUALIFIED/DISQUALIFIED can be reached without any
contact, so they stay false.
"""
from alembic import op
import sqlalchemy as sa


revision = '4d2a7e9c1b56'
down_revision = '3c9f1e5a7b43'
branch_labels = None
depends_on = None

_ALREADY_CONTACTED_STATUSES = ("CONTACTED", "QUALIFYING", "QUALIFIED", "NURTURING", "CONVERTED")


def upgrade() -> None:
    op.add_column(
        'lead', sa.Column('contacted', sa.Boolean(), nullable=False, server_default=sa.false()))
    statuses = ", ".join(f"'{s}'" for s in _ALREADY_CONTACTED_STATUSES)
    op.execute(f"UPDATE lead SET contacted = true WHERE status IN ({statuses})")


def downgrade() -> None:
    op.drop_column('lead', 'contacted')
