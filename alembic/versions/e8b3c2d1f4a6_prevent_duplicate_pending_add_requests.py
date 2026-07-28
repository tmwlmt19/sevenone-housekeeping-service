"""prevent duplicate pending add requests

At most one pending *add* request per staff email / room number in a hotel.
The identity of an add lives in the JSONB payload (no row exists yet), so these
are expression indexes over `payload ->> 'email'` / `payload ->> 'room_number'`.
Mirrors uq_access_requests_pending_remove; the router also returns a friendly
409 before the insert would trip these.

Revision ID: e8b3c2d1f4a6
Revises: 975cc75a3fb4
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e8b3c2d1f4a6'
down_revision = '975cc75a3fb4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        'uq_access_requests_pending_add_staff',
        'access_requests',
        [sa.text('hotel_id'), sa.text("(payload ->> 'email')")],
        unique=True,
        postgresql_where=sa.text(
            "status = 'pending' AND kind = 'add' AND resource = 'staff'"
        ),
    )
    op.create_index(
        'uq_access_requests_pending_add_room',
        'access_requests',
        [sa.text('hotel_id'), sa.text("(payload ->> 'room_number')")],
        unique=True,
        postgresql_where=sa.text(
            "status = 'pending' AND kind = 'add' AND resource = 'room'"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        'uq_access_requests_pending_add_room', table_name='access_requests'
    )
    op.drop_index(
        'uq_access_requests_pending_add_staff', table_name='access_requests'
    )
