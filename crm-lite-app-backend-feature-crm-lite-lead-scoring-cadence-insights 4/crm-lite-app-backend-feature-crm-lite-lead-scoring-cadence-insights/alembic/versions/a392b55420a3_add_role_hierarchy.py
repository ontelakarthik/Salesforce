"""add role hierarchy

Adds the admin-configurable Role Hierarchy: a self-referencing
parent_role_id on `role` (the Profile table). Purely additive — every
existing profile defaults to NULL (top-level/unplaced), so this is a
zero-behavior-change migration: a flat tree behaves identically to today
until an admin actually sets a parent via PATCH /admin/profiles/{id}.

Revision ID: a392b55420a3
Revises: f469eb05be31
Create Date: 2026-08-28 11:11:03.949733
"""
from alembic import op
import sqlalchemy as sa


revision = 'a392b55420a3'
down_revision = 'f469eb05be31'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('role', sa.Column('parent_role_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_role_parent_role_id_role', 'role', 'role', ['parent_role_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_role_parent_role_id_role', 'role', type_='foreignkey')
    op.drop_column('role', 'parent_role_id')
