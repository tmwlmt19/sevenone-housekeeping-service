from typing import TYPE_CHECKING

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.room import Room
    from app.models.task import Task
    from app.models.user import User


class Hotel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "hotels"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)

    users: Mapped[list["User"]] = relationship(
        back_populates="hotel", cascade="all, delete-orphan"
    )
    rooms: Mapped[list["Room"]] = relationship(
        back_populates="hotel", cascade="all, delete-orphan"
    )
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="hotel", cascade="all, delete-orphan"
    )
