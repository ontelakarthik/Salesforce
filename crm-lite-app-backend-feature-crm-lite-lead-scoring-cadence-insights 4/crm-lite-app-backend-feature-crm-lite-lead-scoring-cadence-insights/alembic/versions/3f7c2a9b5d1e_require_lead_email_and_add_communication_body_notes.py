"""require lead.contact_email and add communication.body/notes

Lead/Sales Communication requirements (Phase 1):

- lead.contact_email is now required (see crm_models.LeadCreate/LeadUpdate's
  new format validation, and crm_service.create_lead()) -- email is a core
  communication channel for Leads and the cadence/follow-up functionality
  depends on it. Any pre-existing lead with no email is backfilled with a
  synthetic, unique placeholder address before the NOT NULL constraint is
  applied, rather than blocking the migration on manual data cleanup.
- communication.body -- full message content (both directions for EMAIL
  rows: what was actually sent/received, not just the subject; free-text
  notes for CALL rows via the separate `notes` column below) so a rep can
  open a logged email/call from a Lead's Activity History and read its
  complete content, not just its subject line.
- communication.notes -- free-text notes for a logged Communication (e.g.
  Log a Call's Notes field), kept separate from `subject` and `body`.

Revision ID: 3f7c2a9b5d1e
Revises: 9d25ed664447
Create Date: 2026-09-12 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '3f7c2a9b5d1e'
down_revision = '9d25ed664447'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Backfill before adding NOT NULL -- a unique placeholder per row so it
    # never collides with a real address (and stays recognizably synthetic).
    op.execute(
        "UPDATE lead SET contact_email = 'lead-' || id::text || '@unknown.invalid' "
        "WHERE contact_email IS NULL"
    )
    op.alter_column('lead', 'contact_email', existing_type=sa.String(length=255), nullable=False)

    op.add_column('communication', sa.Column('body', sa.Text(), nullable=True))
    op.add_column('communication', sa.Column('notes', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('communication', 'notes')
    op.drop_column('communication', 'body')
    op.alter_column('lead', 'contact_email', existing_type=sa.String(length=255), nullable=True)
