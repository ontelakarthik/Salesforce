"""add communication provider_message_id unique index

Revision ID: 3c9f1e5a7b43
Revises: 2b8e0d4f6a32
Create Date: 2026-09-21 00:00:00.000000

Required for WhatsApp/SMS inbound-webhook idempotency (see
crm_service.process_inbound_sms() and the planned WhatsApp equivalent,
which already do an application-level find_by_provider_message_id() check
before insert — but that's a check-then-act race under concurrent Twilio
retries; this migration adds the real database-level guarantee).

Safety: provider_message_id already has real data in it today (Twilio SMS
SIDs). Blindly adding a unique index over an already-populated column that
might contain duplicates is exactly the kind of migration that can corrupt
a production rollout, so upgrade() checks for existing duplicate non-null
values FIRST and raises — aborting the migration transaction with nothing
changed — rather than creating the index outright or silently touching any
existing row. If this raises, do NOT edit this migration to work around
it: investigate the specific communication.id groups named in the error
message, resolve the duplicates by hand (or confirm they're intentional
and this constraint needs rethinking), then re-run `alembic upgrade head`.
"""
from alembic import op
import sqlalchemy as sa


revision = '3c9f1e5a7b43'
down_revision = '2b8e0d4f6a32'
branch_labels = None
depends_on = None

_INDEX_NAME = "ix_communication_provider_message_id_unique"

_DUPLICATE_CHECK_SQL = sa.text("""
    SELECT provider_message_id, array_agg(id ORDER BY id) AS communication_ids, count(*) AS n
    FROM communication
    WHERE provider_message_id IS NOT NULL
    GROUP BY provider_message_id
    HAVING count(*) > 1
""")


def upgrade() -> None:
    bind = op.get_bind()
    duplicates = bind.execute(_DUPLICATE_CHECK_SQL).fetchall()
    if duplicates:
        lines = "\n".join(
            f"  provider_message_id={row.provider_message_id!r} -> {row.n} rows, "
            f"communication.id in {list(row.communication_ids)}"
            for row in duplicates
        )
        raise RuntimeError(
            "Refusing to create a unique index on communication.provider_message_id: "
            f"{len(duplicates)} duplicate value(s) already exist.\n{lines}\n"
            "No row was deleted or modified. For each group above, determine whether "
            "it is a legitimate existing record (e.g. a manually re-logged "
            "communication that happens to share a SID) or a genuine data issue, "
            "resolve it by hand, then re-run `alembic upgrade head`."
        )
    op.create_index(
        _INDEX_NAME,
        "communication",
        ["provider_message_id"],
        unique=True,
        postgresql_where=sa.text("provider_message_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="communication")
