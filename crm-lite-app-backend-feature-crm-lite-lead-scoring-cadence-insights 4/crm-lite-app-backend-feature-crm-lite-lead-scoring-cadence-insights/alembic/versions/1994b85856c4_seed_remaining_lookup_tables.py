"""seed remaining lookup tables

Reference data (not mock business data) — every lookup table each module's
business logic depends on, matching models.enums.* one-to-one.

Revision ID: 1994b85856c4
Revises: a3bdd2f85a83
Create Date: 2026-07-23 15:11:29.709106
"""
from alembic import op
import sqlalchemy as sa


revision = '1994b85856c4'
down_revision = 'a3bdd2f85a83'
branch_labels = None
depends_on = None

contact_type = sa.table(
    "contact_type", sa.column("code", sa.String), sa.column("display_name", sa.String))
opportunity_stage = sa.table(
    "opportunity_stage", sa.column("code", sa.String), sa.column("display_name", sa.String),
    sa.column("is_terminal", sa.Boolean))
agreement_type = sa.table(
    "agreement_type", sa.column("code", sa.String), sa.column("display_name", sa.String),
    sa.column("default_sla_hours", sa.Integer))
agreement_status = sa.table(
    "agreement_status", sa.column("code", sa.String), sa.column("display_name", sa.String),
    sa.column("is_terminal", sa.Boolean))
project_status = sa.table(
    "project_status", sa.column("code", sa.String), sa.column("display_name", sa.String),
    sa.column("is_terminal", sa.Boolean))
role = sa.table(
    "role", sa.column("code", sa.String), sa.column("display_name", sa.String))

CONTACT_TYPE = [
    {"code": "BUSINESS", "display_name": "Business"},
    {"code": "LEGAL", "display_name": "Legal"},
    {"code": "PROCUREMENT", "display_name": "Procurement"},
]
OPPORTUNITY_STAGE = [
    {"code": "NEW", "display_name": "New", "is_terminal": False},
    {"code": "QUALIFIED", "display_name": "Qualified", "is_terminal": False},
    {"code": "PROPOSAL", "display_name": "Proposal", "is_terminal": False},
    {"code": "NEGOTIATION", "display_name": "Negotiation", "is_terminal": False},
    {"code": "WON", "display_name": "Won", "is_terminal": True},
    {"code": "LOST", "display_name": "Lost", "is_terminal": True},
]
AGREEMENT_TYPE = [
    {"code": "NDA", "display_name": "NDA", "default_sla_hours": 48},
    {"code": "MSA", "display_name": "MSA", "default_sla_hours": 120},
    {"code": "SOW", "display_name": "SOW", "default_sla_hours": 72},
    {"code": "VENDOR_MSA", "display_name": "Vendor MSA", "default_sla_hours": 120},
    {"code": "PURCHASE_ORDER", "display_name": "Purchase Order", "default_sla_hours": 24},
]
AGREEMENT_STATUS = [
    {"code": "DRAFT", "display_name": "Draft", "is_terminal": False},
    {"code": "REVIEW", "display_name": "Under review", "is_terminal": False},
    {"code": "APPROVED", "display_name": "Approved", "is_terminal": False},
    {"code": "SENT", "display_name": "Sent", "is_terminal": False},
    {"code": "SIGNED", "display_name": "Signed", "is_terminal": False},
    {"code": "EXPIRED", "display_name": "Expired", "is_terminal": True},
    {"code": "SUPERSEDED", "display_name": "Superseded", "is_terminal": True},
]
PROJECT_STATUS = [
    {"code": "PLANNING", "display_name": "Planning", "is_terminal": False},
    {"code": "ACTIVE", "display_name": "Active", "is_terminal": False},
    {"code": "CLOSED", "display_name": "Closed", "is_terminal": True},
]
ROLE = [
    {"code": "SALES", "display_name": "Sales"},
    {"code": "ACCOUNT_EXEC", "display_name": "Account Executive"},
    {"code": "LEADERSHIP", "display_name": "Leadership"},
    {"code": "ADMIN", "display_name": "Admin"},
]


def upgrade() -> None:
    op.bulk_insert(contact_type, CONTACT_TYPE)
    op.bulk_insert(opportunity_stage, OPPORTUNITY_STAGE)
    op.bulk_insert(agreement_type, AGREEMENT_TYPE)
    op.bulk_insert(agreement_status, AGREEMENT_STATUS)
    op.bulk_insert(project_status, PROJECT_STATUS)
    op.bulk_insert(role, ROLE)


def downgrade() -> None:
    for table, seed in (
        (contact_type, CONTACT_TYPE), (opportunity_stage, OPPORTUNITY_STAGE),
        (agreement_type, AGREEMENT_TYPE), (agreement_status, AGREEMENT_STATUS),
        (project_status, PROJECT_STATUS), (role, ROLE),
    ):
        codes = tuple(row["code"] for row in seed)
        op.execute(table.delete().where(table.c.code.in_(codes)))
