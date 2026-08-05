"""add hotel_api_keys (per-hotel PMS API keys)

Revision ID: c3d5e7f9a1b2
Revises: b2e4f6a8c1d0
Create Date: 2026-07-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d5e7f9a1b2'
down_revision: Union[str, None] = 'b2e4f6a8c1d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'hotel_api_keys',
        sa.Column('hotel_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('key_prefix', sa.String(length=32), nullable=False),
        sa.Column('key_hash', sa.String(length=64), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'id', sa.UUID(), server_default=sa.text('gen_random_uuid()'),
            nullable=False,
        ),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.ForeignKeyConstraint(['hotel_id'], ['hotels.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_hotel_api_keys_hotel_id'),
        'hotel_api_keys', ['hotel_id'], unique=False,
    )
    op.create_index(
        op.f('ix_hotel_api_keys_key_hash'),
        'hotel_api_keys', ['key_hash'], unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_hotel_api_keys_key_hash'), table_name='hotel_api_keys',
    )
    op.drop_index(
        op.f('ix_hotel_api_keys_hotel_id'), table_name='hotel_api_keys',
    )
    op.drop_table('hotel_api_keys')
