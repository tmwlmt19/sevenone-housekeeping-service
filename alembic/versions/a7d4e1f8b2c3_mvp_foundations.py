"""mvp foundations: front_desk role, pending_approval status, hotel
auto_approve_tasks, room last_cleaned_by

Revision ID: a7d4e1f8b2c3
Revises: b2e4f6a8c1d0
Create Date: 2026-07-23 00:00:00.000000

Note: this branches from the same parent (b2e4f6a8c1d0) as the PMS-import
migration (c3d5e7f9a1b2) on the feature/pms-bulk-task-import branch. When both
land on staging there will be two Alembic heads — reconcile with
`alembic merge heads` (or re-parent one) before deploying.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7d4e1f8b2c3'
down_revision: Union[str, None] = 'b2e4f6a8c1d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New enum values. PostgreSQL 12+ permits ADD VALUE inside a transaction as
    # long as the new value isn't *used* in the same transaction (it isn't here).
    op.execute(
        "ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'front_desk' AFTER 'manager'"
    )
    op.execute(
        "ALTER TYPE task_status ADD VALUE IF NOT EXISTS 'pending_approval' "
        "AFTER 'in_progress'"
    )

    # Per-hotel toggle: when true, a housekeeper completing a task is auto-approved
    # (straight to completed) instead of going to pending_approval for review.
    op.add_column(
        'hotels',
        sa.Column(
            'auto_approve_tasks',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
        ),
    )

    # Accountability: the housekeeper who last completed a cleaning task here.
    op.add_column('rooms', sa.Column('last_cleaned_by', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_rooms_last_cleaned_by',
        'rooms',
        'users',
        ['last_cleaned_by'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_rooms_last_cleaned_by', 'rooms', type_='foreignkey')
    op.drop_column('rooms', 'last_cleaned_by')
    op.drop_column('hotels', 'auto_approve_tasks')
    # Enum values (front_desk, pending_approval) are intentionally left in place:
    # PostgreSQL can't drop an enum value without recreating the type.
