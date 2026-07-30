"""add floor_maps, room_placements, floor_decorations (interactive floor map)

Three purpose-scoped tables backing the interactive hotel floor map:
  * floor_maps        — one row per (hotel, floor): canvas extent in feet + snap
                        grid.
  * room_placements   — 1:1 with a placed room (room_id IS the pk): its x/y/w/h
                        footprint + rotation, in integer feet.
  * floor_decorations — non-room chrome on the canvas (halls / stairs / elevators
                        / lobby / labels), each an addressable row so a cleaning
                        task can eventually target one.

`rooms` stays the source of truth for identity + status + floor; layout lives in
these tables so existing rooms queries are untouched. No backfill — existing
rooms have no placement until someone maps them.
See sevenone-docs/housekeeping/hotel-map-plan.md §2.

Revision ID: f1c3a5b7d9e2
Revises: e8b3c2d1f4a6
Create Date: 2026-07-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1c3a5b7d9e2'
down_revision: Union[str, None] = 'e8b3c2d1f4a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'floor_maps',
        sa.Column('hotel_id', sa.UUID(), nullable=False),
        sa.Column('floor', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=True),
        sa.Column('width_ft', sa.Integer(), nullable=False),
        sa.Column('height_ft', sa.Integer(), nullable=False),
        sa.Column(
            'grid_ft', sa.SmallInteger(),
            server_default=sa.text('1'), nullable=False,
        ),
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
        sa.UniqueConstraint(
            'hotel_id', 'floor', name='uq_floor_map_hotel_floor',
        ),
    )
    op.create_index(
        op.f('ix_floor_maps_hotel_id'),
        'floor_maps', ['hotel_id'], unique=False,
    )
    op.create_table(
        'room_placements',
        sa.Column('room_id', sa.UUID(), nullable=False),
        sa.Column('x', sa.Integer(), nullable=False),
        sa.Column('y', sa.Integer(), nullable=False),
        sa.Column('w', sa.Integer(), nullable=False),
        sa.Column('h', sa.Integer(), nullable=False),
        sa.Column(
            'rotation', sa.SmallInteger(),
            server_default=sa.text('0'), nullable=False,
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.ForeignKeyConstraint(['room_id'], ['rooms.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('room_id'),
    )
    op.create_table(
        'floor_decorations',
        sa.Column('floor_map_id', sa.UUID(), nullable=False),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('x', sa.Integer(), nullable=False),
        sa.Column('y', sa.Integer(), nullable=False),
        sa.Column('w', sa.Integer(), nullable=False),
        sa.Column('h', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=80), nullable=True),
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
        sa.ForeignKeyConstraint(
            ['floor_map_id'], ['floor_maps.id'], ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_floor_decorations_floor_map_id'),
        'floor_decorations', ['floor_map_id'], unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_floor_decorations_floor_map_id'),
        table_name='floor_decorations',
    )
    op.drop_table('floor_decorations')
    op.drop_table('room_placements')
    op.drop_index(op.f('ix_floor_maps_hotel_id'), table_name='floor_maps')
    op.drop_table('floor_maps')
