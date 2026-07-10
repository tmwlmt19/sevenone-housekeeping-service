"""add user UI preferences (theme, preferred_language)

Revision ID: 9c1d4e7a2b58
Revises: 7f3a9c2b1e04
Create Date: 2026-07-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9c1d4e7a2b58'
down_revision: Union[str, None] = '7f3a9c2b1e04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column(
            'theme',
            sa.String(length=10),
            nullable=False,
            server_default='system',
        ),
    )
    op.add_column(
        'users',
        sa.Column(
            'preferred_language',
            sa.String(length=5),
            nullable=False,
            server_default='en',
        ),
    )


def downgrade() -> None:
    op.drop_column('users', 'preferred_language')
    op.drop_column('users', 'theme')
