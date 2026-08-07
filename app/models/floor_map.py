import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.hotel import Hotel
    from app.models.room import Room


class FloorMap(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One saved layout per (hotel, floor): the canvas extent, snap grid, and the
    floor's own outline polygon.

    Rooms are NOT stored here — they stay in `rooms` and are positioned via
    `room_placements`; non-room chrome lives in `floor_decorations`. This row holds
    the floor's dimensions + shape, so every existing rooms query is untouched. A
    floor with rooms but no `floor_maps` row simply hasn't been mapped yet.
    """

    __tablename__ = "floor_maps"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        UniqueConstraint("hotel_id", "floor", name="uq_floor_map_hotel_floor"),
    )

    hotel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hotels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Matches rooms.floor (a nullable int); one map targets one floor.
    floor: Mapped[int] = mapped_column(Integer, nullable=False)
    # Optional human label, e.g. "Ground Floor", "Tower 2".
    name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Canvas / viewBox extent, in feet. The outline sits inside this box.
    width_ft: Mapped[int] = mapped_column(Integer, nullable=False)
    height_ft: Mapped[int] = mapped_column(Integer, nullable=False)
    # Snap increment in feet for the editor's drag/resize.
    grid_ft: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("1"), default=1
    )
    # The floor's shape: an ordered list of [x, y] float-foot vertices. NULL means
    # a plain width_ft × height_ft rectangle (so pre-polygon maps still render).
    outline: Mapped[list[list[float]] | None] = mapped_column(JSONB, nullable=True)

    hotel: Mapped["Hotel"] = relationship(back_populates="floor_maps")
    decorations: Mapped[list["FloorDecoration"]] = relationship(
        back_populates="floor_map", cascade="all, delete-orphan"
    )


class RoomPlacement(Base):
    """Where a room sits on its floor's canvas — 1:1 with a *placed* room, the
    room id IS the primary key.

    Kept separate from `rooms` so identity/status queries stay free of nullable
    layout fields; a room with no placement row is "unplaced" and surfaces in the
    editor's tray to be dragged in. Geometry is an absolute polygon (float feet);
    a rectangle is just four right-angle vertices. Only `updated_at` is tracked —
    a placement's creation moment isn't meaningful.
    """

    __tablename__ = "room_placements"
    __mapper_args__ = {"eager_defaults": True}

    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rooms.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # The room's footprint: an ordered list of [x, y] float-foot vertices (>= 3).
    # Rotation is baked into the vertices — there is no separate angle column.
    vertices: Mapped[list[list[float]]] = mapped_column(JSONB, nullable=False)
    # The room's door as an edge-relative reference {edge, t} — which wall (index
    # into `vertices`) and where along it (0..1). Stays glued to the wall through
    # moves/rotations; the future connection to the corridor network. NULL until
    # a door is placed.
    door: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    room: Mapped["Room"] = relationship(back_populates="placement")


class FloorDecoration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A non-room shape on a floor's canvas — a hallway, stairwell, elevator,
    lobby, or free text label.

    A first-class row (not embedded JSONB) so each decoration has a stable id: it
    can be addressed individually and, in a later phase, be the target of a
    cleaning task the way a room is. `kind` is a short code validated against the
    API's DecorationKind enum but stored as varchar (like room_type), so adding a
    new kind needs no DB migration. Geometry is an absolute polygon (float feet),
    like a room; the one exception is a `label`, whose `vertices` is a single
    [x, y] anchor point for its text.
    """

    __tablename__ = "floor_decorations"
    __mapper_args__ = {"eager_defaults": True}

    floor_map_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("floor_maps.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    # Ordered [x, y] float-foot vertices (>= 3 for a shape; a single anchor point
    # for a `label`).
    vertices: Mapped[list[list[float]]] = mapped_column(JSONB, nullable=False)
    label: Mapped[str | None] = mapped_column(String(80), nullable=True)

    floor_map: Mapped["FloorMap"] = relationship(back_populates="decorations")
