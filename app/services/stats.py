"""Write-time rollups behind the stats dashboard.

Every operational event that a stat depends on — a task assigned, a clean
finished, a shift closed — increments a small per-housekeeper-per-day rollup row
here, inside the same transaction as the operational write. Reads then become a
cheap ``SUM(...) GROUP BY`` over the rollup tables for any date window. See
docs/housekeeping/stats-dashboard-plan.md.

All helpers are additive upserts (`INSERT ... ON CONFLICT (grain) DO UPDATE SET
col = col + excluded.col`) and never commit — the caller owns the transaction.
"""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.shift import Shift
from app.models.stats import HousekeeperDailyStats, HousekeeperRoomTypeDailyStats

# Bucket for a null/blank room type in the per-room-type rollup (NULLs can't be
# part of a primary key / conflict target).
UNKNOWN_ROOM_TYPE = "UNKNOWN"


def stat_date_for(moment: datetime) -> date:
    """The UTC calendar date a timestamp rolls up into (v1 buckets by UTC day —
    add hotels.timezone later if day boundaries need to be local)."""
    return moment.astimezone(timezone.utc).date()


def normalize_room_type(room_type: str | None) -> str:
    """Room types are stored already trimmed+uppercased; fold null/blank to the
    UNKNOWN bucket so it's a valid, groupable key."""
    return (room_type or "").strip().upper() or UNKNOWN_ROOM_TYPE


async def _incr_daily(
    db: AsyncSession,
    *,
    hotel_id: uuid.UUID,
    housekeeper_id: uuid.UUID,
    stat_date: date,
    increments: dict[str, int],
) -> None:
    """Upsert one housekeeper_daily_stats row, adding each named delta."""
    values = {
        "hotel_id": hotel_id,
        "housekeeper_id": housekeeper_id,
        "stat_date": stat_date,
        **increments,
    }
    stmt = insert(HousekeeperDailyStats).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["hotel_id", "housekeeper_id", "stat_date"],
        set_={
            col: getattr(HousekeeperDailyStats, col) + getattr(stmt.excluded, col)
            for col in increments
        }
        | {"updated_at": func.now()},
    )
    await db.execute(stmt)


async def record_assignments(
    db: AsyncSession,
    *,
    hotel_id: uuid.UUID,
    housekeeper_id: uuid.UUID,
    count: int = 1,
    at: datetime | None = None,
) -> None:
    """Count `count` tasks newly handed to a housekeeper (create-with-assignee,
    reassign, redistribute, bulk import). A reassigned task counts for the new
    owner — this is the "work handed to you" signal the load chart shows."""
    if count <= 0:
        return
    await _incr_daily(
        db,
        hotel_id=hotel_id,
        housekeeper_id=housekeeper_id,
        stat_date=stat_date_for(at or datetime.now(timezone.utc)),
        increments={"tasks_assigned": count},
    )


async def record_clean(
    db: AsyncSession,
    *,
    hotel_id: uuid.UUID,
    housekeeper_id: uuid.UUID,
    room_type: str | None,
    started_at: datetime | None,
    finished_at: datetime,
) -> None:
    """Record one finished clean. `finished_at` is when the housekeeper marked the
    work done (submitted for approval, or completed directly) — NOT a later
    manager approval, so approval latency never inflates the measured clean time.
    Cleans with no start are counted as completions but excluded from timing."""
    duration = None
    if started_at is not None:
        secs = int((finished_at - started_at).total_seconds())
        if secs >= 0:
            duration = secs
    timed = duration is not None

    await _incr_daily(
        db,
        hotel_id=hotel_id,
        housekeeper_id=housekeeper_id,
        stat_date=stat_date_for(finished_at),
        increments={
            "tasks_completed": 1,
            "clean_seconds_total": duration if timed else 0,
            "clean_count": 1 if timed else 0,
        },
    )

    if not timed:
        return

    stmt = insert(HousekeeperRoomTypeDailyStats).values(
        hotel_id=hotel_id,
        housekeeper_id=housekeeper_id,
        stat_date=stat_date_for(finished_at),
        room_type=normalize_room_type(room_type),
        clean_seconds_total=duration,
        clean_count=1,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["hotel_id", "housekeeper_id", "stat_date", "room_type"],
        set_={
            "clean_seconds_total": (
                HousekeeperRoomTypeDailyStats.clean_seconds_total
                + stmt.excluded.clean_seconds_total
            ),
            "clean_count": (
                HousekeeperRoomTypeDailyStats.clean_count + stmt.excluded.clean_count
            ),
            "updated_at": func.now(),
        },
    )
    await db.execute(stmt)


async def record_shift_close(db: AsyncSession, shift: Shift) -> None:
    """Roll a just-closed shift into the day it ended. All shift time feeds the
    utilization denominator; only shifts that had assigned work count toward the
    efficiency ratio (so an idle clock-in doesn't drag efficiency down)."""
    if shift.ended_at is None:
        return
    seconds = int((shift.ended_at - shift.started_at).total_seconds())
    if seconds < 0:
        seconds = 0
    worked = 1 if (shift.assigned_count or 0) > 0 else 0
    all_done = 1 if shift.all_assigned_done else 0
    await _incr_daily(
        db,
        hotel_id=shift.hotel_id,
        housekeeper_id=shift.housekeeper_id,
        stat_date=stat_date_for(shift.ended_at),
        increments={
            "shift_seconds_total": seconds,
            "shifts_count": 1,
            "shifts_worked": worked,
            "shifts_all_done": all_done,
        },
    )
