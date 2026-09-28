"""expand lead status stages

Revision ID: 90869f9eea5a
Revises: d584fcd72357
Create Date: 2026-08-26 12:00:00.000000
"""
from alembic import op

revision = '90869f9eea5a'
down_revision = 'd584fcd72357'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # lead.status is a plain string column (see models.enums.LeadStatus's
    # docstring) — no schema change, only a data migration. The old flat
    # NEW/WORKING/QUALIFIED/CONVERTED/DISQUALIFIED set becomes an 8-stage
    # model; WORKING's closest conceptual match in the new set is
    # ATTEMPTING_CONTACT ("reached out, no two-way conversation yet" —
    # exactly what WORKING meant). Every other existing value (NEW,
    # QUALIFIED, CONVERTED, DISQUALIFIED) keeps its literal code unchanged.
    op.execute("UPDATE lead SET status = 'ATTEMPTING_CONTACT' WHERE status = 'WORKING'")


def downgrade() -> None:
    op.execute("UPDATE lead SET status = 'WORKING' WHERE status = 'ATTEMPTING_CONTACT'")
    # CONTACTED/QUALIFYING/NURTURING/UNQUALIFIED never existed pre-upgrade —
    # collapse them back to their nearest pre-8-stage equivalent so a
    # downgrade never leaves a row holding a status the old app build
    # wouldn't recognize.
    op.execute("UPDATE lead SET status = 'WORKING' WHERE status IN ('CONTACTED', 'QUALIFYING', 'NURTURING')")
    op.execute("UPDATE lead SET status = 'DISQUALIFIED' WHERE status = 'UNQUALIFIED'")
