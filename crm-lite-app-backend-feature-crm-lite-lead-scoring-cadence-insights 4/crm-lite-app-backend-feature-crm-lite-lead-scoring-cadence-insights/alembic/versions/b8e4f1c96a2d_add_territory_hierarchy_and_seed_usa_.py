"""add territory hierarchy (parent_territory_id) and seed USA/Canada region territories

Salesforce Territory2-inspired hierarchy for the existing Territory master
object (admin_models.Territory) — additive only, reuses the table/API/
service already shipped (no new object, no duplicate CRUD):

- territory.parent_territory_id (nullable, self-referencing FK) -- lets a
  Territory optionally have a parent, e.g. "USA" as the parent of
  "USA - West". NULL means top-level, same zero-behavior-change default as
  Profile.parent_role_id (the existing hierarchy precedent this mirrors).
- Backfills country on the two rows already seeded by 9d25ed664447 (USA/
  CANADA, both previously NULL): USA row -> country='USA', CANADA row ->
  country='Canada' (src/utils/geo.py's exact COUNTRY_USA/COUNTRY_CANADA
  strings; note the CANADA row's own `code` stays "CANADA" — only its new
  `country` value uses geo.py's "Canada" casing). Both keep region=NULL --
  a country-wide territory legitimately has no single region (this
  migration also relaxes region from required-always to optional-when-
  given at the service layer, in the same commit as this migration; see
  admin_service._validate_territory_fields()).
- Seeds one child territory per that country's real geo.py region (never
  invented/approximated names), parented to the corresponding country row:
  USA -> Northeast/Midwest/South/West (4, geo.py's exact
  _US_REGION_BY_STATE values); Canada -> Atlantic/Central/Prairies/West/
  North (5, geo.py's exact _CANADA_REGION_BY_PROVINCE values -- "Central"
  here is this territory's *display name* only, its `region` column is set
  to geo.py's real "Central Canada" string so it still validates against
  utils.geo.valid_regions()). All seeded with code=NULL, demonstrating (and
  exercising) that Territory.code is genuinely optional, per this feature's
  explicit requirement that Territory Code must never be a relationship
  key or a required field.

Revision ID: b8e4f1c96a2d
Revises: 7a4e9c2f6b18
Create Date: 2026-09-17 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'b8e4f1c96a2d'
down_revision = '7a4e9c2f6b18'
branch_labels = None
depends_on = None

# (display_name, region) pairs, in the exact casing geo.py's own region
# vocabulary uses (see utils.geo.valid_regions("USA") / valid_regions("Canada")).
_USA_CHILDREN = [
    ("USA - Northeast", "Northeast"),
    ("USA - Midwest", "Midwest"),
    ("USA - South", "South"),
    ("USA - West", "West"),
]
_CANADA_CHILDREN = [
    ("Canada - Atlantic", "Atlantic"),
    ("Canada - Central", "Central Canada"),
    ("Canada - Prairies", "Prairies"),
    ("Canada - West", "West"),
    ("Canada - North", "North"),
]


def upgrade() -> None:
    op.add_column('territory', sa.Column('parent_territory_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_territory_parent_territory_id', 'territory', 'territory',
        ['parent_territory_id'], ['id'])

    op.execute("UPDATE territory SET country = 'USA' WHERE code = 'USA'")
    op.execute("UPDATE territory SET country = 'Canada' WHERE code = 'CANADA'")

    for display_name, region in _USA_CHILDREN:
        op.execute(sa.text(
            "INSERT INTO territory (display_name, region, is_active, country, parent_territory_id) "
            "SELECT :display_name, :region, true, 'USA', id FROM territory WHERE code = 'USA'"
        ).bindparams(display_name=display_name, region=region))

    for display_name, region in _CANADA_CHILDREN:
        op.execute(sa.text(
            "INSERT INTO territory (display_name, region, is_active, country, parent_territory_id) "
            "SELECT :display_name, :region, true, 'Canada', id FROM territory WHERE code = 'CANADA'"
        ).bindparams(display_name=display_name, region=region))


def downgrade() -> None:
    names = [n for n, _ in _USA_CHILDREN] + [n for n, _ in _CANADA_CHILDREN]
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM territory WHERE display_name IN :names").bindparams(
            sa.bindparam('names', expanding=True)),
        {"names": names},
    )
    op.execute("UPDATE territory SET country = NULL WHERE code IN ('USA', 'CANADA')")
    op.drop_constraint('fk_territory_parent_territory_id', 'territory', type_='foreignkey')
    op.drop_column('territory', 'parent_territory_id')
