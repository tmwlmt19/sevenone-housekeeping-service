"""add tasks.archived_at (clear/soft-archive completed tasks)

Revision ID: d1a2b3c4e5f6
Revises: a7d4e1f8b2c3
Create Date: 2026-07-23 00:00:00.000000

Soft-archive column for "clear completed tasks": clearing sets archived_at so the
row (and its "last cleaned by" credit) is kept but hidden from the default task
list. See docs/housekeeping/roles-and-permissions.md.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1a2b3c4e5f6'
down_revision: Union[str, None] = 'a7d4e1f8b2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'tasks',
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('tasks', 'archived_at')
