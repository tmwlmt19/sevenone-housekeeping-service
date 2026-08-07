"""add shifts + stats rollups, and tasks.started_at

Backs the stats dashboard (see docs/housekeeping/stats-dashboard-plan.md). All
additive: a nullable tasks.started_at, a shifts table, and two write-time
per-housekeeper daily rollups.

Revision ID: c7f2a9d4b6e1
Revises: b4d9f1e6c2a7
Create Date: 2026-08-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7f2a9d4b6e1'
down_revision: Union[str, None] = 'b4d9f1e6c2a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- tasks.started_at ----------------------------------------------------
    op.add_column(
        'tasks',
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    )

    # --- shifts --------------------------------------------------------------
    op.create_table(
        'shifts',
        sa.Column('hotel_id', sa.UUID(), nullable=False),
        sa.Column('housekeeper_id', sa.UUID(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'close_reason',
            sa.Enum(
                'logout', 'stale_reclock', 'daily_cap', 'manual',
                name='shift_close_reason',
            ),
            nullable=True,
        ),
        sa.Column('assigned_count', sa.Integer(), nullable=True),
        sa.Column('completed_count', sa.Integer(), nullable=True),
        sa.Column('all_assigned_done', sa.Boolean(), nullable=True),
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
            ['housekeeper_id'], ['users.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_shifts_hotel_id'), 'shifts', ['hotel_id'], unique=False,
    )
    op.create_index(
        op.f('ix_shifts_housekeeper_id'),
        'shifts', ['housekeeper_id'], unique=False,
    )
    # At most one open shift per housekeeper.
    op.create_index(
        'uq_open_shift_per_housekeeper',
        'shifts', ['housekeeper_id'], unique=True,
        postgresql_where=sa.text('ended_at IS NULL'),
    )

    # --- housekeeper_daily_stats (rollup) ------------------------------------
    op.create_table(
        'housekeeper_daily_stats',
        sa.Column('hotel_id', sa.UUID(), nullable=False),
        sa.Column('housekeeper_id', sa.UUID(), nullable=False),
        sa.Column('stat_date', sa.Date(), nullable=False),
        sa.Column(
            'tasks_assigned', sa.Integer(),
            server_default='0', nullable=False,
        ),
        sa.Column(
            'tasks_completed', sa.Integer(),
            server_default='0', nullable=False,
        ),
        sa.Column(
            'clean_seconds_total', sa.BigInteger(),
            server_default='0', nullable=False,
        ),
        sa.Column(
            'clean_count', sa.Integer(),
            server_default='0', nullable=False,
        ),
        sa.Column(
            'shift_seconds_total', sa.BigInteger(),
            server_default='0', nullable=False,
        ),
        sa.Column(
            'shifts_count', sa.Integer(),
            server_default='0', nullable=False,
        ),
        sa.Column(
            'shifts_worked', sa.Integer(),
            server_default='0', nullable=False,
        ),
        sa.Column(
            'shifts_all_done', sa.Integer(),
            server_default='0', nullable=False,
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
            ['housekeeper_id'], ['users.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('hotel_id', 'housekeeper_id', 'stat_date'),
    )

    # --- housekeeper_roomtype_daily_stats (rollup) ---------------------------
    op.create_table(
        'housekeeper_roomtype_daily_stats',
        sa.Column('hotel_id', sa.UUID(), nullable=False),
        sa.Column('housekeeper_id', sa.UUID(), nullable=False),
        sa.Column('stat_date', sa.Date(), nullable=False),
        sa.Column('room_type', sa.String(length=20), nullable=False),
        sa.Column(
            'clean_seconds_total', sa.BigInteger(),
            server_default='0', nullable=False,
        ),
        sa.Column(
            'clean_count', sa.Integer(),
            server_default='0', nullable=False,
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
            ['housekeeper_id'], ['users.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint(
            'hotel_id', 'housekeeper_id', 'stat_date', 'room_type'
        ),
    )


def downgrade() -> None:
    op.drop_table('housekeeper_roomtype_daily_stats')
    op.drop_table('housekeeper_daily_stats')
    op.drop_index('uq_open_shift_per_housekeeper', table_name='shifts')
    op.drop_index(op.f('ix_shifts_housekeeper_id'), table_name='shifts')
    op.drop_index(op.f('ix_shifts_hotel_id'), table_name='shifts')
    op.drop_table('shifts')
    op.execute("DROP TYPE IF EXISTS shift_close_reason")
    op.drop_column('tasks', 'started_at')
