"""add whatsapp template and communication whatsapp fields

Revision ID: 2b8e0d4f6a32
Revises: 1a7f9c3d5e21
Create Date: 2026-09-21 00:00:00.000000

New whatsapp_template table (approved Twilio Content Templates — see
models/activity_models.py's WhatsAppTemplate for the field-by-field
rationale) plus six new nullable columns on communication for WhatsApp
delivery-status/template/media tracking. Bundled into one migration since
they're one feature and whatsapp_template must exist before communication's
FK to it — same bundling fa86cf5ee990 used for call_disposition + its new
Communication columns.

delivery_status/failure_code are new ground: no prior delivery-status
tracking existed on this table (Twilio SMS status callbacks were never
wired up), so these are generic enough (queued/sent/delivered/read/failed/
undelivered) a future SMS status callback could reuse them too.
template_variables is a Text column holding a JSON-encoded string, not a
native JSON/JSONB column, matching this project's existing convention of
no JSON column type anywhere.
"""
from alembic import op
import sqlalchemy as sa


revision = '2b8e0d4f6a32'
down_revision = '1a7f9c3d5e21'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('whatsapp_template',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('content_sid', sa.String(length=64), nullable=False),
        sa.Column('language', sa.String(length=10), nullable=False),
        sa.Column('category', sa.String(length=20), nullable=False),
        sa.Column('body_preview', sa.String(length=1000), nullable=True),
        sa.Column('variable_count', sa.Integer(), nullable=False),
        sa.Column('approval_status', sa.String(length=20), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.String(length=64), nullable=True),
        sa.Column('updated_by', sa.String(length=64), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('content_sid'),
    )

    op.add_column('communication', sa.Column('delivery_status', sa.String(length=20), nullable=True))
    op.add_column('communication', sa.Column('failure_code', sa.String(length=20), nullable=True))
    op.add_column('communication', sa.Column('whatsapp_template_id', sa.UUID(), nullable=True))
    op.add_column('communication', sa.Column('template_variables', sa.Text(), nullable=True))
    op.add_column('communication', sa.Column('media_url', sa.String(length=500), nullable=True))
    op.add_column('communication', sa.Column('media_content_type', sa.String(length=100), nullable=True))
    op.create_foreign_key('fk_communication_whatsapp_template_id', 'communication',
                          'whatsapp_template', ['whatsapp_template_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_communication_whatsapp_template_id', 'communication', type_='foreignkey')
    op.drop_column('communication', 'media_content_type')
    op.drop_column('communication', 'media_url')
    op.drop_column('communication', 'template_variables')
    op.drop_column('communication', 'whatsapp_template_id')
    op.drop_column('communication', 'failure_code')
    op.drop_column('communication', 'delivery_status')
    op.drop_table('whatsapp_template')
