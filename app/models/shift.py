import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ShiftCloseReason, pg_enum

if TYPE_CHECKING:
    from app.models.hotel import Hotel
    from app.models.user import User


class Shift(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One housekeeper's work session, opened at clock-in and closed at logout.

    Efficiency (did they finish everything assigned?) and utilization (how much of
    the shift was spent cleaning?) are both scored against these rows. To keep the
    reads cheap the per-shift outcome (assigned/completed/all-done) is snapshotted
    onto the row at close and rolled into `housekeeper_daily_stats`; see
    app/services/shifts.py and stats-dashboard-plan.md."""

    __tablename__ = "shifts"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        # At most one open shift per housekeeper at a time (clock-in closes any
        # stale open one first, so this also guards against a double clock-in).
        Index(
            "uq_open_shift_per_housekeeper",
            "housekeeper_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
    )

    hotel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hotels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    housekeeper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Null while the housekeeper is still on shift.
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    close_reason: Mapped[ShiftCloseReason | None] = mapped_column(
        pg_enum(ShiftCloseReason, "shift_close_reason"), nullable=True
    )
    # Efficiency snapshot, computed once at close (see services/shifts.py):
    # how many rooms/tasks were the housekeeper's during the shift, and how many
    # they completed. `all_assigned_done` is the efficiency numerator.
    assigned_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    all_assigned_done: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    hotel: Mapped["Hotel"] = relationship()
    housekeeper: Mapped["User"] = relationship()
