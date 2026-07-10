"""add access_requests (manager -> admin approval queue)

Revision ID: 7f3a9c2b1e04
Revises: 3cf711188863
Create Date: 2026-07-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '7f3a9c2b1e04'
down_revision: Union[str, None] = '3cf711188863'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'access_requests',
        sa.Column('hotel_id', sa.UUID(), nullable=False),
        sa.Column(
            'resource',
            sa.Enum('staff', 'room', name='request_resource'),
            nullable=False,
        ),
        sa.Column(
            'kind',
            sa.Enum('add', 'remove', name='request_kind'),
            nullable=False,
        ),
        sa.Column(
            'status',
            sa.Enum(
                'pending', 'approved', 'rejected', name='request_status'
            ),
            nullable=False,
        ),
        sa.Column('requested_by', sa.UUID(), nullable=True),
        sa.Column('target_id', sa.UUID(), nullable=True),
        sa.Column('payload', postgresql.JSONB(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('decision_note', sa.Text(), nullable=True),
        sa.Column('decided_by', sa.UUID(), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ['requested_by'], ['users.id'], ondelete='SET NULL'
        ),
        sa.ForeignKeyConstraint(
            ['decided_by'], ['users.id'], ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_access_requests_hotel_id'),
        'access_requests', ['hotel_id'], unique=False,
    )
    op.create_index(
        op.f('ix_access_requests_status'),
        'access_requests', ['status'], unique=False,
    )
    # At most one pending remove request per target user/room.
    op.create_index(
        'uq_access_requests_pending_remove',
        'access_requests', ['resource', 'target_id'], unique=True,
        postgresql_where=sa.text("status = 'pending' AND kind = 'remove'"),
    )


def downgrade() -> None:
    op.drop_index(
        'uq_access_requests_pending_remove', table_name='access_requests'
    )
    op.drop_index(
        op.f('ix_access_requests_status'), table_name='access_requests'
    )
    op.drop_index(
        op.f('ix_access_requests_hotel_id'), table_name='access_requests'
    )
    op.drop_table('access_requests')

    # Drop the Postgres enum types that create_table implicitly created.
    for enum_name in ('request_status', 'request_kind', 'request_resource'):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
