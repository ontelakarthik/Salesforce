"""seed customer_type lookup values

Reference data (not mock business data) — the four codes CRM's business
logic depends on (see models.enums.CustomerType / services/crm_service.py).
Every other module's lookup tables (contact_type, agreement_type,
agreement_status, opportunity_stage, project_status, role) are left for
whoever implements that module's business logic to seed the same way.

Revision ID: a3bdd2f85a83
Revises: a26422db02d6
Create Date: 2026-07-23 15:01:42.476891
"""
from alembic import op
import sqlalchemy as sa


revision = 'a3bdd2f85a83'
down_revision = 'a26422db02d6'
branch_labels = None
depends_on = None

customer_type = sa.table(
    "customer_type",
    sa.column("code", sa.String),
    sa.column("display_name", sa.String),
)

SEED = [
    {"code": "PROSPECT", "display_name": "Prospect"},
    {"code": "CLIENT", "display_name": "Client"},
    {"code": "VENDOR", "display_name": "Vendor"},
    {"code": "PARTNER", "display_name": "Partner"},
]


def upgrade() -> None:
    op.bulk_insert(customer_type, SEED)


def downgrade() -> None:
    codes = tuple(row["code"] for row in SEED)
    op.execute(customer_type.delete().where(customer_type.c.code.in_(codes)))
