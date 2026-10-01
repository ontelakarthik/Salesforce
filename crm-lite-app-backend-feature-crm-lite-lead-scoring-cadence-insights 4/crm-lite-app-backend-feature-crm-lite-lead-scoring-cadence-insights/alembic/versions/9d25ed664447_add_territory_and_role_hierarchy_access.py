"""add sales territory/region and extend record access with role hierarchy

Salesforce-style Sales Territory/Region — a business access-control/
assignment concept, deliberately separate from (and never auto-equated
with) Account/Lead's existing Billing Country/State (see src/utils/geo.py,
untouched by this migration). Additive only:

- territory table -- id/code/display_name/is_active, plain lookup shape
  (no audit/soft-delete columns), same as account_type/contact_type/
  opportunity_stage. Seeded with exactly USA and CANADA, both active, per
  this feature's initial scope. Managed via the existing generic
  /admin/lookups/territory endpoints (admin_service._LOOKUP_TABLES) --
  no bespoke CRUD.
- employee.territory_id (nullable FK -> territory.id) -- part of an
  employee's assignment/authorization data (see admin_models.Employee).
- account.territory_id / lead.territory_id (nullable FK -> territory.id) --
  defaulted at create time from the record's resolved owner's
  Employee.territory_id (see crm_service.create_account()/create_lead());
  never auto-recomputed afterward, same treatment as Account.
  first_contact_at.

Does NOT add a new capability and does NOT change any org_wide_default row:
Territory is deliberately not a sharing/grant mechanism on its own (see
services/record_access_service.py's module docstring) -- this migration
only adds the columns/table needed to store and default it. The
corresponding code change (this same feature) extends
record_access_service.can_user_access_record() to also honor Role
Hierarchy (CurrentUser.subordinate_employee_ids()) for LEAD/ACCOUNT/
CONTACT/OPPORTUNITY/CAMPAIGN -- a pure Python-layer change with no schema
impact, called out here only for context.

Revision ID: 9d25ed664447
Revises: c9a1e5f7b3d6
Create Date: 2026-09-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '9d25ed664447'
down_revision = 'c9a1e5f7b3d6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- territory -----------------------------------------------------------
    op.create_table(
        'territory',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('code', sa.String(length=32), nullable=False),
        sa.Column('display_name', sa.String(length=120), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
    )
    territory = sa.table(
        'territory',
        sa.column('code', sa.String),
        sa.column('display_name', sa.String),
        sa.column('is_active', sa.Boolean),
    )
    op.bulk_insert(territory, [
        {'code': 'USA', 'display_name': 'USA', 'is_active': True},
        {'code': 'CANADA', 'display_name': 'Canada', 'is_active': True},
    ])

    # --- employee.territory_id ------------------------------------------------
    op.add_column('employee', sa.Column('territory_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_employee_territory_id', 'employee', 'territory', ['territory_id'], ['id'])

    # --- account.territory_id -------------------------------------------------
    op.add_column('account', sa.Column('territory_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_account_territory_id', 'account', 'territory', ['territory_id'], ['id'])

    # --- lead.territory_id -----------------------------------------------------
    op.add_column('lead', sa.Column('territory_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_lead_territory_id', 'lead', 'territory', ['territory_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_lead_territory_id', 'lead', type_='foreignkey')
    op.drop_column('lead', 'territory_id')
    op.drop_constraint('fk_account_territory_id', 'account', type_='foreignkey')
    op.drop_column('account', 'territory_id')
    op.drop_constraint('fk_employee_territory_id', 'employee', type_='foreignkey')
    op.drop_column('employee', 'territory_id')
    op.drop_table('territory')
