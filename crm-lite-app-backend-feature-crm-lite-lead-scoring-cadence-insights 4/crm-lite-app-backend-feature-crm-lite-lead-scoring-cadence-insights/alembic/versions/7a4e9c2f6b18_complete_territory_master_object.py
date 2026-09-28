"""complete territory master object (name/code/description/country/region/status)

Extends the existing `territory` table (added by 9d25ed664447) into a full
master data object per the Territory feature spec, WITHOUT creating a second
Territory or Region table/system:

- territory.code: NOT NULL -> nullable. Territory's `code` is optional
  (unlike every other lookup table's `code`) since a Territory is
  meaningfully identified by Name/Country/Region alone. The existing unique
  constraint on `code` is left exactly as-is (Postgres allows any number of
  NULLs under a unique constraint), so this does NOT add a new constraint —
  it only relaxes NOT NULL, and only for this table.
- territory.description: new, nullable free-text column.
- territory.country: new, nullable column. Validated at the service layer
  (admin_service._validate_territory_fields) against the same supported-
  country set Account/Lead already use (see src/utils/geo.py) — no new
  Country reference table.
- territory.region: new, nullable column. Validated at the service layer
  against utils.geo.valid_regions(country) — the exact Region vocabulary
  Lead/Account's derived Region field already uses (see geo.py's
  _REGION_BY_STATE_PROVINCE_BY_COUNTRY) — reused as-is, not duplicated.

country/region are nullable at the DB level purely so the two rows already
seeded by 9d25ed664447 (USA/CANADA — country-wide territories with no single
Region) don't need fabricated values invented for them; every territory
created or edited through the API from this point on is required (at the
service layer) to supply both. No existing row is modified or deleted.

Revision ID: 7a4e9c2f6b18
Revises: 3f7c2a9b5d1e
Create Date: 2026-09-15 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '7a4e9c2f6b18'
down_revision = '3f7c2a9b5d1e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('territory', 'code', existing_type=sa.String(length=32), nullable=True)
    op.add_column('territory', sa.Column('description', sa.String(length=500), nullable=True))
    op.add_column('territory', sa.Column('country', sa.String(length=64), nullable=True))
    op.add_column('territory', sa.Column('region', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('territory', 'region')
    op.drop_column('territory', 'country')
    op.drop_column('territory', 'description')
    op.alter_column('territory', 'code', existing_type=sa.String(length=32), nullable=False)
