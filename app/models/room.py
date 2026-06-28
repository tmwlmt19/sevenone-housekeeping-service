import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import RoomStatus, pg_enum

if TYPE_CHECKING:
    from app.models.hotel import Hotel
    from app.models.task import Task


class Room(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rooms"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        UniqueConstraint("hotel_id", "room_number", name="uq_room_hotel_number"),
    )

    hotel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hotels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    room_number: Mapped[str] = mapped_column(String(50), nullable=False)
    floor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Short code (e.g. 'STD', 'STE', 'DLX'); validated at the API layer so hotels
    # can define custom types without a migration.
    room_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[RoomStatus] = mapped_column(
        pg_enum(RoomStatus, "room_status"),
        nullable=False,
        default=RoomStatus.CLEAN,
    )

    hotel: Mapped["Hotel"] = relationship(back_populates="rooms")
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )
