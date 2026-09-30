"""backfill sales opportunity capabilities

The prior migration (a04a019aaaf4) reseeded leads.read/accounts.read/
opportunities.read wherever a profile held platform.read, and
X.create/X.edit/X.delete wherever it held X.write, computed from the
role_capability rows granted at THAT migration's run time. Production
diagnostics found SALES currently holds both opportunities.write and
platform.read (and correctly has the equivalent leads.*/accounts.* fine-
grained keys) but is missing all four opportunities.create/edit/delete/read
rows -- something re-saved SALES's capability set after that migration ran
without carrying the new keys forward (Profiles/Object Permissions both do
a full-replace-per-profile save), silently regressing SALES's own
Opportunities access (dashboard, list, detail all 403 for a SALES-only
profile) despite the profile's own description explicitly covering
"opportunities and proposals".

Rather than hand-patch SALES by name, this reruns the same IMPLICATIONS
backfill against the CURRENT role_capability rows for every profile --
idempotent (skips pairs already granted), so it both fixes today's SALES
drift and self-heals the same class of gap for any other profile without
guessing why the drift happened.

Revision ID: 4281f80e8018
Revises: a04a019aaaf4
Create Date: 2026-08-28 19:12:40.202062
"""
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '4281f80e8018'
down_revision = 'a04a019aaaf4'
branch_labels = None
depends_on = None

IMPLICATIONS = {
    "leads.write": ("leads.create", "leads.edit", "leads.delete"),
    "accounts.write": ("accounts.create", "accounts.edit"),
    "opportunities.write": ("opportunities.create", "opportunities.edit", "opportunities.delete"),
    "platform.read": ("leads.read", "accounts.read", "opportunities.read"),
}


def upgrade() -> None:
    conn = op.get_bind()
    granted = conn.execute(sa.text(
        "SELECT role_id, capability_key FROM role_capability WHERE deleted_at IS NULL")).fetchall()
    granted_set = {(row[0], row[1]) for row in granted}

    role_capability = sa.table(
        "role_capability",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("role_id", sa.Integer),
        sa.column("capability_key", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(timezone.utc)
    new_rows = []
    seen_new: set[tuple[int, str]] = set()

    def add(role_id: int, key: str) -> None:
        pair = (role_id, key)
        if pair in granted_set or pair in seen_new:
            return
        seen_new.add(pair)
        new_rows.append({"id": uuid.uuid4(), "role_id": role_id, "capability_key": key,
                         "created_at": now, "updated_at": now})

    for role_id, old_key in granted_set:
        for new_key in IMPLICATIONS.get(old_key, ()):
            add(role_id, new_key)

    if new_rows:
        op.bulk_insert(role_capability, new_rows)


def downgrade() -> None:
    # No-op: this migration only ever fills gaps already implied by
    # a04a019aaaf4's data model (holding X.write/platform.read implies the
    # fine-grained keys); downgrading that migration already deletes every
    # row with one of these capability_key values regardless of which
    # migration inserted it.
    pass
