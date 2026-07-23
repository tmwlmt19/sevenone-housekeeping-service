from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.hotel_api_key import HotelApiKey
    from app.models.room import Room
    from app.models.task import Task
    from app.models.user import User


class Hotel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "hotels"
    # Fetch server-side defaults (UUID, timestamps) via RETURNING so attributes
    # are never left expired — avoids lazy IO under async sessions.
    __mapper_args__ = {"eager_defaults": True}

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    # When true, a housekeeper completing a task is auto-approved (straight to
    # completed) instead of going to pending_approval for manager/front-desk review.
    auto_approve_tasks: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )

    users: Mapped[list["User"]] = relationship(
        back_populates="hotel", cascade="all, delete-orphan"
    )
    rooms: Mapped[list["Room"]] = relationship(
        back_populates="hotel", cascade="all, delete-orphan"
    )
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="hotel", cascade="all, delete-orphan"
    )
    api_keys: Mapped[list["HotelApiKey"]] = relationship(
        back_populates="hotel", cascade="all, delete-orphan"
    )
