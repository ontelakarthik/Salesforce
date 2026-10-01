"""seed missing contact_type lookup values

1994b85856c4 seeded contact_type with only BUSINESS/LEGAL/PROCUREMENT — the
frontend (types/schema.ts's ContactTypeLookup, the ER-diagram mirror) has
always offered FINANCE/TECHNICAL too, so picking either in the Contacts form
fails with "Unknown contact_type" since the row never existed. Adds the two
missing codes; guarded against re-insertion since this table's `code` column
is unique and some environments may have added them by hand already.

Revision ID: 60fa6cb5e8be
Revises: 5749ba6b408e
Create Date: 2026-08-06 15:38:41.108646
"""
from alembic import op
import sqlalchemy as sa


revision = '60fa6cb5e8be'
down_revision = '5749ba6b408e'
branch_labels = None
depends_on = None

contact_type = sa.table(
    "contact_type", sa.column("code", sa.String), sa.column("display_name", sa.String))

_NEW_CODES = [("FINANCE", "Finance"), ("TECHNICAL", "Technical")]


def upgrade() -> None:
    conn = op.get_bind()
    existing = {row[0] for row in conn.execute(sa.select(contact_type.c.code))}
    to_insert = [{"code": code, "display_name": display_name}
                for code, display_name in _NEW_CODES if code not in existing]
    if to_insert:
        op.bulk_insert(contact_type, to_insert)


def downgrade() -> None:
    conn = op.get_bind()
    for code, _display_name in _NEW_CODES:
        conn.execute(contact_type.delete().where(contact_type.c.code == code))
