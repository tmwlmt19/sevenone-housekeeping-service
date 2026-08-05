import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import TaskPriority, TaskStatus, pg_enum

if TYPE_CHECKING:
    from app.models.hotel import Hotel
    from app.models.room import Room
    from app.models.user import User


class Task(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tasks"
    __mapper_args__ = {"eager_defaults": True}

    hotel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hotels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rooms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[TaskStatus] = mapped_column(
        pg_enum(TaskStatus, "task_status"),
        nullable=False,
        default=TaskStatus.PENDING,
    )
    priority: Mapped[TaskPriority] = mapped_column(
        pg_enum(TaskPriority, "task_priority"),
        nullable=False,
        default=TaskPriority.NORMAL,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Set when a manager/front-desk "clears" a completed task off the board. The
    # row is kept (soft archive) so "last cleaned by" and history survive; cleared
    # tasks are simply hidden from the default task list.
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    hotel: Mapped["Hotel"] = relationship(back_populates="tasks")
    room: Mapped["Room"] = relationship(back_populates="tasks")
    assignee: Mapped["User | None"] = relationship(
        back_populates="assigned_tasks", foreign_keys=[assigned_to]
    )
