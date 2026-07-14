"""add password_reset_tokens (self-service forgot-password)

Revision ID: b2e4f6a8c1d0
Revises: 9c1d4e7a2b58
Create Date: 2026-07-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2e4f6a8c1d0'
down_revision: Union[str, None] = '9c1d4e7a2b58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'password_reset_tokens',
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'id', sa.UUID(), server_default=sa.text('gen_random_uuid()'),
            nullable=False,
        ),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_password_reset_tokens_user_id'),
        'password_reset_tokens', ['user_id'], unique=False,
    )
    op.create_index(
        op.f('ix_password_reset_tokens_token_hash'),
        'password_reset_tokens', ['token_hash'], unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_password_reset_tokens_token_hash'),
        table_name='password_reset_tokens',
    )
    op.drop_index(
        op.f('ix_password_reset_tokens_user_id'),
        table_name='password_reset_tokens',
    )
    op.drop_table('password_reset_tokens')
