"""make users.hotel_id nullable (service admins have no hotel)

Revision ID: 3cf711188863
Revises: 4ff3d312f88b
Create Date: 2026-07-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3cf711188863'
down_revision: Union[str, None] = '4ff3d312f88b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('users', 'hotel_id', existing_type=sa.UUID(), nullable=True)


def downgrade() -> None:
    # Reverting requires every user to have a hotel; will fail if any admin is
    # currently hotel-less.
    op.alter_column('users', 'hotel_id', existing_type=sa.UUID(), nullable=False)
