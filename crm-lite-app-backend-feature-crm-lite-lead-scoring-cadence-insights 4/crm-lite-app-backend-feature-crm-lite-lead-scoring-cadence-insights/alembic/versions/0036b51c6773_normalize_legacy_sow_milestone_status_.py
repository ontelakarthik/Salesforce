"""normalize legacy sow_milestone status values

The frontend's stale mock-era status vocabulary (PENDING/COMPLETE) leaked
into some seeded rows before the real PLANNED->DELIVERED->INVOICED->PAID
state machine existed. Both legacy values are unambiguous from each row's
own data: COMPLETE rows already have actual_date set but no invoice_ref/
invoiced_at (-> DELIVERED, not PAID); PENDING rows have neither set and are
future-dated (-> PLANNED). Without this normalization, any row still on a
legacy value would be stuck with an empty transition set once the new
status state machine ships, since neither value is a recognized state.

Revision ID: 0036b51c6773
Revises: 494af20b2c20
Create Date: 2026-08-04 08:54:15.146710
"""
from alembic import op


revision = '0036b51c6773'
down_revision = '494af20b2c20'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE sow_milestone SET status = 'PLANNED' WHERE status = 'PENDING'")
    op.execute("UPDATE sow_milestone SET status = 'DELIVERED' WHERE status = 'COMPLETE'")


def downgrade() -> None:
    # Legacy values are not restorable (would need to know which normalized
    # rows were originally PENDING vs. PLANNED, or DELIVERED vs. COMPLETE).
    pass
