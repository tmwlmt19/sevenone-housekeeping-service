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
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.hotel import Hotel
    from app.models.room import Room


class FloorMap(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One saved layout per (hotel, floor): the canvas extent and snap grid.

    Rooms are NOT stored here — they stay in `rooms` and are positioned via
    `room_placements`; non-room chrome lives in `floor_decorations`. This row only
    holds the floor's dimensions, so every existing rooms query is untouched. A
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
    # Canvas extent, in feet ("nearest foot" precision).
    width_ft: Mapped[int] = mapped_column(Integer, nullable=False)
    height_ft: Mapped[int] = mapped_column(Integer, nullable=False)
    # Snap increment in feet for the editor's drag/resize.
    grid_ft: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("1"), default=1
    )

    hotel: Mapped["Hotel"] = relationship(back_populates="floor_maps")
    decorations: Mapped[list["FloorDecoration"]] = relationship(
        back_populates="floor_map", cascade="all, delete-orphan"
    )


class RoomPlacement(Base):
    """Where a room sits on its floor's canvas — 1:1 with a *placed* room, the
    room id IS the primary key.

    Kept separate from `rooms` so identity/status queries stay free of nullable
    layout fields; a room with no placement row is "unplaced" and surfaces in the
    editor's tray to be dragged in. All geometry is integer feet. Only
    `updated_at` is tracked — a placement's creation moment isn't meaningful.
    """

    __tablename__ = "room_placements"
    __mapper_args__ = {"eager_defaults": True}

    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rooms.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # Top-left corner on the floor canvas, in feet.
    x: Mapped[int] = mapped_column(Integer, nullable=False)
    y: Mapped[int] = mapped_column(Integer, nullable=False)
    # Footprint, in feet.
    w: Mapped[int] = mapped_column(Integer, nullable=False)
    h: Mapped[int] = mapped_column(Integer, nullable=False)
    # Degrees; v1 uses 0 / 90 / 180 / 270.
    rotation: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0"), default=0
    )
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
    new kind needs no DB migration. Geometry is integer feet; decorations are
    axis-aligned in v1 (no rotation).
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
    # Top-left corner + footprint on the floor canvas, in feet. A label may have
    # a zero footprint (it's just anchored text).
    x: Mapped[int] = mapped_column(Integer, nullable=False)
    y: Mapped[int] = mapped_column(Integer, nullable=False)
    w: Mapped[int] = mapped_column(Integer, nullable=False)
    h: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String(80), nullable=True)

    floor_map: Mapped["FloorMap"] = relationship(back_populates="decorations")
