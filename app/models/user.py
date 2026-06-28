import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import UserRole, pg_enum

if TYPE_CHECKING:
    from app.models.hotel import Hotel
    from app.models.task import Task


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __mapper_args__ = {"eager_defaults": True}

    hotel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hotels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        pg_enum(UserRole, "user_role"), nullable=False
    )

    hotel: Mapped["Hotel"] = relationship(back_populates="users")
    assigned_tasks: Mapped[list["Task"]] = relationship(
        back_populates="assignee", foreign_keys="Task.assigned_to"
    )
