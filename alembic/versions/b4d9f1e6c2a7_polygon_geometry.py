"""polygon geometry for the floor map (vertices, door, outline)

Moves floor-map geometry from axis-aligned rects to absolute polygons so the
mapper can describe angled wings, L-shaped floors, and arbitrary shapes:

  * room_placements  — replace (x, y, w, h, rotation) with `vertices` (JSONB) and
                       add `door` (JSONB, an [x, y] point for later path routing).
  * floor_decorations — replace (x, y, w, h) with `vertices` (JSONB); a `label`
                       stores a single anchor point.
  * floor_maps       — add `outline` (JSONB): the floor's own polygon; NULL means
                       a plain width_ft × height_ft rectangle.

Existing rows are backfilled: each rect (with its right-angle rotation folded in)
becomes four absolute vertices, so no saved map is lost. Downgrade collapses each
polygon back to its bounding-box rect (lossy for non-rectangular shapes).

See sevenone-docs/housekeeping/hotel-map-plan.md.

Revision ID: b4d9f1e6c2a7
Revises: f1c3a5b7d9e2
Create Date: 2026-08-05
"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b4d9f1e6c2a7'
down_revision: Union[str, None] = 'f1c3a5b7d9e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _rect_to_vertices(x, y, w, h, rotation=0):
    """Four absolute corners of a w×h rect at (x, y). A right-angle rotation is
    folded into the footprint by swapping w/h about the center (kept self-contained
    so this migration never depends on app code that may change later)."""
    eff_w, eff_h = (h, w) if rotation % 180 == 90 else (w, h)
    cx, cy = x + w / 2, y + h / 2
    nx, ny = cx - eff_w / 2, cy - eff_h / 2
    return [
        [round(nx, 2), round(ny, 2)],
        [round(nx + eff_w, 2), round(ny, 2)],
        [round(nx + eff_w, 2), round(ny + eff_h, 2)],
        [round(nx, 2), round(ny + eff_h, 2)],
    ]


def _bbox(vertices):
    xs = [p[0] for p in vertices]
    ys = [p[1] for p in vertices]
    return min(xs), min(ys), max(xs), max(ys)


def upgrade() -> None:
    conn = op.get_bind()

    # --- room_placements: rect+rotation -> vertices, plus a door point ---
    op.add_column(
        'room_placements',
        sa.Column('vertices', postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        'room_placements',
        sa.Column('door', postgresql.JSONB(), nullable=True),
    )
    for row in conn.execute(
        sa.text('SELECT room_id, x, y, w, h, rotation FROM room_placements')
    ).fetchall():
        verts = _rect_to_vertices(row.x, row.y, row.w, row.h, row.rotation)
        conn.execute(
            sa.text(
                'UPDATE room_placements SET vertices = CAST(:v AS JSONB) '
                'WHERE room_id = :id'
            ),
            {'v': json.dumps(verts), 'id': row.room_id},
        )
    op.alter_column('room_placements', 'vertices', nullable=False)
    op.drop_column('room_placements', 'rotation')
    op.drop_column('room_placements', 'x')
    op.drop_column('room_placements', 'y')
    op.drop_column('room_placements', 'w')
    op.drop_column('room_placements', 'h')

    # --- floor_decorations: rect -> vertices (label -> single anchor point) ---
    op.add_column(
        'floor_decorations',
        sa.Column('vertices', postgresql.JSONB(), nullable=True),
    )
    for row in conn.execute(
        sa.text('SELECT id, kind, x, y, w, h FROM floor_decorations')
    ).fetchall():
        if row.kind == 'label':
            verts = [[round(row.x, 2), round(row.y, 2)]]
        else:
            # Guard against legacy zero-size shapes so we never store 0-area.
            verts = _rect_to_vertices(row.x, row.y, row.w or 1, row.h or 1)
        conn.execute(
            sa.text(
                'UPDATE floor_decorations SET vertices = CAST(:v AS JSONB) '
                'WHERE id = :id'
            ),
            {'v': json.dumps(verts), 'id': row.id},
        )
    op.alter_column('floor_decorations', 'vertices', nullable=False)
    op.drop_column('floor_decorations', 'x')
    op.drop_column('floor_decorations', 'y')
    op.drop_column('floor_decorations', 'w')
    op.drop_column('floor_decorations', 'h')

    # --- floor_maps: add the outline polygon (NULL = rectangle) ---
    op.add_column(
        'floor_maps',
        sa.Column('outline', postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    conn = op.get_bind()

    op.drop_column('floor_maps', 'outline')

    # --- floor_decorations: vertices -> bounding-box rect ---
    op.add_column('floor_decorations', sa.Column('x', sa.Integer(), nullable=True))
    op.add_column('floor_decorations', sa.Column('y', sa.Integer(), nullable=True))
    op.add_column('floor_decorations', sa.Column('w', sa.Integer(), nullable=True))
    op.add_column('floor_decorations', sa.Column('h', sa.Integer(), nullable=True))
    for row in conn.execute(
        sa.text('SELECT id, kind, vertices FROM floor_decorations')
    ).fetchall():
        verts = row.vertices
        if row.kind == 'label' or len(verts) < 2:
            x, y, w, h = verts[0][0], verts[0][1], 0, 0
        else:
            min_x, min_y, max_x, max_y = _bbox(verts)
            x, y, w, h = min_x, min_y, max_x - min_x, max_y - min_y
        conn.execute(
            sa.text(
                'UPDATE floor_decorations SET x = :x, y = :y, w = :w, h = :h '
                'WHERE id = :id'
            ),
            {'x': round(x), 'y': round(y), 'w': round(w), 'h': round(h), 'id': row.id},
        )
    for col in ('x', 'y', 'w', 'h'):
        op.alter_column('floor_decorations', col, nullable=False)
    op.drop_column('floor_decorations', 'vertices')

    # --- room_placements: vertices -> bounding-box rect, rotation 0 ---
    op.add_column('room_placements', sa.Column('x', sa.Integer(), nullable=True))
    op.add_column('room_placements', sa.Column('y', sa.Integer(), nullable=True))
    op.add_column('room_placements', sa.Column('w', sa.Integer(), nullable=True))
    op.add_column('room_placements', sa.Column('h', sa.Integer(), nullable=True))
    op.add_column(
        'room_placements',
        sa.Column(
            'rotation', sa.SmallInteger(),
            server_default=sa.text('0'), nullable=False,
        ),
    )
    for row in conn.execute(
        sa.text('SELECT room_id, vertices FROM room_placements')
    ).fetchall():
        min_x, min_y, max_x, max_y = _bbox(row.vertices)
        conn.execute(
            sa.text(
                'UPDATE room_placements SET x = :x, y = :y, w = :w, h = :h '
                'WHERE room_id = :id'
            ),
            {
                'x': round(min_x), 'y': round(min_y),
                'w': round(max_x - min_x), 'h': round(max_y - min_y),
                'id': row.room_id,
            },
        )
    for col in ('x', 'y', 'w', 'h'):
        op.alter_column('room_placements', col, nullable=False)
    op.drop_column('room_placements', 'door')
    op.drop_column('room_placements', 'vertices')
