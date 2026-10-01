"""add agreement initiated_by_employee_id, notification recipient and message

Replaces Agreement.initiated_by (a free-text string, never reliably an FK)
with initiated_by_employee_id so the AE who created an agreement can be
notified when it's signed. Any existing initiated_by value that already
looks like a UUID and matches a real employee row is carried over before the
column is dropped. Also adds Notification.recipient_employee_id/message so a
notification can be targeted at one person with a human-readable message,
instead of only ever being a broadcast row nobody's code created.

Revision ID: 5749ba6b408e
Revises: 0036b51c6773
Create Date: 2026-08-06 14:41:59.094022
"""
from alembic import op
import sqlalchemy as sa


revision = '5749ba6b408e'
down_revision = '0036b51c6773'
branch_labels = None
depends_on = None

_UUID_RE = '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'


def upgrade() -> None:
    op.add_column('agreement', sa.Column('initiated_by_employee_id', sa.UUID(), nullable=True))

    op.execute(sa.text(
        """
        UPDATE agreement
        SET initiated_by_employee_id = initiated_by::uuid
        WHERE initiated_by ~ :uuid_re
          AND EXISTS (SELECT 1 FROM employee e WHERE e.id = agreement.initiated_by::uuid)
        """
    ).bindparams(uuid_re=_UUID_RE))

    op.create_foreign_key('fk_agreement_initiated_by_employee_id_employee', 'agreement',
                          'employee', ['initiated_by_employee_id'], ['id'])
    op.drop_column('agreement', 'initiated_by')

    op.add_column('notification', sa.Column('recipient_employee_id', sa.UUID(), nullable=True))
    op.add_column('notification', sa.Column('message', sa.String(length=500), nullable=True))
    op.create_foreign_key('fk_notification_recipient_employee_id_employee', 'notification',
                          'employee', ['recipient_employee_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_notification_recipient_employee_id_employee', 'notification',
                       type_='foreignkey')
    op.drop_column('notification', 'message')
    op.drop_column('notification', 'recipient_employee_id')

    op.add_column('agreement', sa.Column('initiated_by', sa.VARCHAR(length=64), nullable=True))
    op.execute(
        "UPDATE agreement SET initiated_by = initiated_by_employee_id::text "
        "WHERE initiated_by_employee_id IS NOT NULL"
    )
    op.drop_constraint('fk_agreement_initiated_by_employee_id_employee', 'agreement',
                       type_='foreignkey')
    op.drop_column('agreement', 'initiated_by_employee_id')
