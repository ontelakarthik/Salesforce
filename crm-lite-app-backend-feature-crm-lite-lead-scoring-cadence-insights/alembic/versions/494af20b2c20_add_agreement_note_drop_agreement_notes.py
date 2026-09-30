"""add agreement_note, drop agreement.notes

Replaces Agreement.notes (a single freeform string) with agreement_note, a
dedicated running-comments table — AuditMixin's created_at/created_by already
give each note its timestamp/commenter metadata. Any existing non-null
Agreement.notes value is carried over as that agreement's first note before
the column is dropped, so no data is silently lost.

Revision ID: 494af20b2c20
Revises: 1994b85856c4
Create Date: 2026-07-31 10:23:09.267723
"""
import uuid

from alembic import op
import sqlalchemy as sa


revision = '494af20b2c20'
down_revision = '1994b85856c4'
branch_labels = None
depends_on = None

agreement_note = sa.table(
    "agreement_note",
    sa.column("id", sa.UUID),
    sa.column("agreement_id", sa.String),
    sa.column("note_text", sa.String),
    sa.column("created_by", sa.String),
    sa.column("updated_by", sa.String),
)


def upgrade() -> None:
    op.create_table('agreement_note',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('agreement_id', sa.String(length=40), nullable=False),
    sa.Column('note_text', sa.String(length=2000), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=True),
    sa.Column('updated_by', sa.String(length=64), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['agreement_id'], ['agreement.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    conn = op.get_bind()
    existing = conn.execute(sa.text(
        "SELECT id, notes, created_by FROM agreement WHERE notes IS NOT NULL"
    )).fetchall()
    if existing:
        op.bulk_insert(agreement_note, [
            {
                "id": uuid.uuid4(), "agreement_id": row.id, "note_text": row.notes,
                "created_by": row.created_by, "updated_by": row.created_by,
            }
            for row in existing
        ])

    op.drop_column('agreement', 'notes')


def downgrade() -> None:
    op.add_column('agreement', sa.Column('notes', sa.VARCHAR(length=2000), autoincrement=False, nullable=True))
    op.drop_table('agreement_note')
