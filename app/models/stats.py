import uuid
from datetime import date

from sqlalchemy import BigInteger, Date, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin


class HousekeeperDailyStats(TimestampMixin, Base):
    """Pre-aggregated per-housekeeper, per-UTC-day rollup — the read model behind
    the stats dashboard. Rows are upserted (incremented) at write-time as tasks
    are assigned/completed and shifts close (see app/services/stats.py), so a
    date-range query is a cheap ``SUM(...) GROUP BY housekeeper`` over small
    tables. Grain = (hotel_id, housekeeper_id, stat_date)."""

    __tablename__ = "housekeeper_daily_stats"

    hotel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hotels.id", ondelete="CASCADE"),
        primary_key=True,
    )
    housekeeper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    stat_date: Mapped[date] = mapped_column(Date, primary_key=True)

    # Load: assignment events to this housekeeper, and cleans they finished.
    tasks_assigned: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0
    )
    tasks_completed: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0
    )
    # Timing: sum + count of *timed* cleans (those with a start), for the overall
    # average clean time and the utilization numerator. Untimed cleans (no start)
    # count in tasks_completed but contribute 0 here.
    clean_seconds_total: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0", default=0
    )
    clean_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0
    )
    # Shifts that ended this day. shift_seconds_total is the utilization
    # denominator (all shift time). shifts_worked = shifts that had assigned work
    # (efficiency denominator); shifts_all_done = of those, how many finished
    # everything (efficiency numerator).
    shift_seconds_total: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0", default=0
    )
    shifts_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0
    )
    shifts_worked: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0
    )
    shifts_all_done: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0
    )


class HousekeeperRoomTypeDailyStats(TimestampMixin, Base):
    """Per-housekeeper, per-day, per-room-type timing rollup — powers "avg clean
    time by room type" (per housekeeper, and hotel-wide when summed across
    housekeepers). Only *timed* cleans are recorded. `room_type` is the snapshot
    taken at completion (uppercased; a null/blank type buckets as 'UNKNOWN').
    Grain = (hotel_id, housekeeper_id, stat_date, room_type)."""

    __tablename__ = "housekeeper_roomtype_daily_stats"

    hotel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hotels.id", ondelete="CASCADE"),
        primary_key=True,
    )
    housekeeper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    stat_date: Mapped[date] = mapped_column(Date, primary_key=True)
    room_type: Mapped[str] = mapped_column(String(20), primary_key=True)

    clean_seconds_total: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0", default=0
    )
    clean_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0
    )
