"""Opening and closing housekeeper shifts.

Clock-in opens a shift; logout (or an explicit clock-out) closes it. Because the
session cookie lives for hours and people forget to log out, `close_shift` caps a
shift's length so a forgotten logout can't produce a runaway utilization
denominator, and clocking in again auto-closes any stale open shift first.

At close we snapshot the shift's efficiency outcome (did the housekeeper finish
everything assigned to them?) and roll the shift into the daily stats.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ShiftCloseReason, TaskStatus
from app.models.shift import Shift
from app.models.task import Task
from app.services import stats

# A shift is never credited as longer than this — bounds a forgotten logout.
MAX_SHIFT_HOURS = 12

# Tasks the housekeeper still has to do (their work isn't finished).
_OPEN_STATUSES = (
    TaskStatus.PENDING,
    TaskStatus.ASSIGNED,
    TaskStatus.IN_PROGRESS,
)


async def get_open_shift(
    db: AsyncSession, *, hotel_id: uuid.UUID, housekeeper_id: uuid.UUID
) -> Shift | None:
    result = await db.execute(
        select(Shift).where(
            Shift.hotel_id == hotel_id,
            Shift.housekeeper_id == housekeeper_id,
            Shift.ended_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def _scalar_count(db: AsyncSession, *whereclauses) -> int:
    result = await db.execute(select(func.count()).select_from(Task).where(*whereclauses))
    return int(result.scalar_one())


async def _efficiency_snapshot(
    db: AsyncSession, shift: Shift, *, ended_at: datetime
) -> tuple[int, int, bool]:
    """(assigned_count, completed_count, all_assigned_done) for a closing shift.

    "Assigned" = the housekeeper's live workload at close: cleans they completed
    during the shift + anything still open + anything awaiting approval. "All
    done" means nothing is still open (awaiting-approval counts as done from the
    housekeeper's side) and they had at least one task."""
    completed = await _scalar_count(
        db,
        Task.assigned_to == shift.housekeeper_id,
        Task.hotel_id == shift.hotel_id,
        Task.completed_at.is_not(None),
        Task.completed_at >= shift.started_at,
        Task.completed_at <= ended_at,
    )
    open_remaining = await _scalar_count(
        db,
        Task.assigned_to == shift.housekeeper_id,
        Task.hotel_id == shift.hotel_id,
        Task.status.in_(_OPEN_STATUSES),
        Task.archived_at.is_(None),
    )
    awaiting_approval = await _scalar_count(
        db,
        Task.assigned_to == shift.housekeeper_id,
        Task.hotel_id == shift.hotel_id,
        Task.status == TaskStatus.PENDING_APPROVAL,
        Task.archived_at.is_(None),
    )
    assigned = completed + open_remaining + awaiting_approval
    all_done = assigned > 0 and open_remaining == 0
    return assigned, completed, all_done


async def close_shift(
    db: AsyncSession,
    shift: Shift,
    *,
    reason: ShiftCloseReason,
    at: datetime | None = None,
) -> Shift:
    """Close an open shift, capping its length, snapshotting efficiency, and
    rolling it into the daily stats. No-op if already closed."""
    if shift.ended_at is not None:
        return shift
    now = at or datetime.now(timezone.utc)
    cap = shift.started_at + timedelta(hours=MAX_SHIFT_HOURS)
    ended_at = min(now, cap)
    if ended_at >= cap and reason == ShiftCloseReason.LOGOUT:
        # The logout arrived past the cap — it was really a forgotten logout.
        reason = ShiftCloseReason.DAILY_CAP

    assigned, completed, all_done = await _efficiency_snapshot(
        db, shift, ended_at=ended_at
    )
    shift.ended_at = ended_at
    shift.close_reason = reason
    shift.assigned_count = assigned
    shift.completed_count = completed
    shift.all_assigned_done = all_done

    await stats.record_shift_close(db, shift)
    return shift


async def clock_in(
    db: AsyncSession, *, hotel_id: uuid.UUID, housekeeper_id: uuid.UUID
) -> Shift:
    """Open a new shift, auto-closing any stale open one first."""
    existing = await get_open_shift(
        db, hotel_id=hotel_id, housekeeper_id=housekeeper_id
    )
    if existing is not None:
        await close_shift(db, existing, reason=ShiftCloseReason.STALE_RECLOCK)
        # Persist the close before opening a new shift so the partial-unique
        # "one open shift per housekeeper" index never sees two open rows.
        await db.flush()

    shift = Shift(
        hotel_id=hotel_id,
        housekeeper_id=housekeeper_id,
        started_at=datetime.now(timezone.utc),
    )
    db.add(shift)
    await db.flush()
    return shift
