"""Read side of the stats dashboard.

Every endpoint is a cheap grouped ``SUM`` over the write-time rollups
(housekeeper_daily_stats / housekeeper_roomtype_daily_stats), scoped to a hotel
and an inclusive [from, to] date window (default: the last 7 days). Manager /
front-desk / admin only — the same audience as the dashboard.
"""

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_manager_or_above, require_same_hotel
from app.models.enums import UserRole
from app.models.stats import HousekeeperDailyStats, HousekeeperRoomTypeDailyStats
from app.models.user import User
from app.schemas.stats import (
    CleanTimesResponse,
    EfficiencyResponse,
    HousekeeperEfficiency,
    HousekeeperLoad,
    HousekeeperRoomTypeAvg,
    RoomTypeAvg,
    TaskLoadResponse,
)

router = APIRouter(prefix="/api/v1/hotels/{hotel_id}/stats", tags=["stats"])

# Default window length when the caller doesn't pass `from`.
_DEFAULT_WINDOW_DAYS = 7


def _resolve_window(
    date_from: date | None, date_to: date | None
) -> tuple[date, date]:
    today = datetime.now(timezone.utc).date()
    to = date_to or today
    frm = date_from or (to - timedelta(days=_DEFAULT_WINDOW_DAYS - 1))
    if frm > to:
        frm, to = to, frm
    return frm, to


def _avg(total_seconds: int, count: int) -> float | None:
    return (total_seconds / count) if count else None


def _pct(numerator: int, denominator: int) -> float | None:
    return (100.0 * numerator / denominator) if denominator else None


async def _housekeepers(
    db: AsyncSession, hotel_id: uuid.UUID
) -> list[tuple[uuid.UUID, str]]:
    """The hotel's housekeepers (id, name), sorted by name — the roster the
    charts render, so people with no activity still show as zero."""
    result = await db.execute(
        select(User.id, User.name)
        .where(User.hotel_id == hotel_id, User.role == UserRole.HOUSEKEEPER)
        .order_by(func.lower(User.name))
    )
    return [(row[0], row[1]) for row in result.all()]


@router.get("/clean-times", response_model=CleanTimesResponse)
async def clean_times(
    hotel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
) -> CleanTimesResponse:
    """Average clean time by room type — hotel-wide and per housekeeper."""
    require_same_hotel(hotel_id, current_user)
    frm, to = _resolve_window(date_from, date_to)
    roster = await _housekeepers(db, hotel_id)

    T = HousekeeperRoomTypeDailyStats
    result = await db.execute(
        select(
            T.housekeeper_id,
            T.room_type,
            func.sum(T.clean_seconds_total),
            func.sum(T.clean_count),
        )
        .where(T.hotel_id == hotel_id, T.stat_date >= frm, T.stat_date <= to)
        .group_by(T.housekeeper_id, T.room_type)
    )

    per_hk: dict[uuid.UUID, list[RoomTypeAvg]] = {}
    hotel_totals: dict[str, tuple[int, int]] = {}
    for hk_id, room_type, secs, count in result.all():
        secs, count = int(secs or 0), int(count or 0)
        per_hk.setdefault(hk_id, []).append(
            RoomTypeAvg(
                room_type=room_type,
                clean_count=count,
                avg_seconds=_avg(secs, count),
            )
        )
        h_secs, h_count = hotel_totals.get(room_type, (0, 0))
        hotel_totals[room_type] = (h_secs + secs, h_count + count)

    hotel_by_room_type = [
        RoomTypeAvg(
            room_type=rt, clean_count=count, avg_seconds=_avg(secs, count)
        )
        for rt, (secs, count) in sorted(hotel_totals.items())
    ]
    by_housekeeper = [
        HousekeeperRoomTypeAvg(
            housekeeper_id=hk_id,
            name=name,
            by_room_type=sorted(
                per_hk.get(hk_id, []), key=lambda r: r.room_type
            ),
        )
        for hk_id, name in roster
    ]
    return CleanTimesResponse(
        from_date=frm,
        to_date=to,
        hotel_by_room_type=hotel_by_room_type,
        by_housekeeper=by_housekeeper,
    )


async def _daily_totals(
    db: AsyncSession, hotel_id: uuid.UUID, frm: date, to: date
) -> dict[uuid.UUID, dict[str, int]]:
    """Summed housekeeper_daily_stats over the window, keyed by housekeeper."""
    D = HousekeeperDailyStats
    result = await db.execute(
        select(
            D.housekeeper_id,
            func.sum(D.tasks_assigned),
            func.sum(D.tasks_completed),
            func.sum(D.clean_seconds_total),
            func.sum(D.shift_seconds_total),
            func.sum(D.shifts_worked),
            func.sum(D.shifts_all_done),
        )
        .where(D.hotel_id == hotel_id, D.stat_date >= frm, D.stat_date <= to)
        .group_by(D.housekeeper_id)
    )
    totals: dict[uuid.UUID, dict[str, int]] = {}
    for row in result.all():
        totals[row[0]] = {
            "tasks_assigned": int(row[1] or 0),
            "tasks_completed": int(row[2] or 0),
            "clean_seconds_total": int(row[3] or 0),
            "shift_seconds_total": int(row[4] or 0),
            "shifts_worked": int(row[5] or 0),
            "shifts_all_done": int(row[6] or 0),
        }
    return totals


@router.get("/efficiency", response_model=EfficiencyResponse)
async def efficiency(
    hotel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
) -> EfficiencyResponse:
    """Per housekeeper: share of worked shifts where they finished every task."""
    require_same_hotel(hotel_id, current_user)
    frm, to = _resolve_window(date_from, date_to)
    roster = await _housekeepers(db, hotel_id)
    totals = await _daily_totals(db, hotel_id, frm, to)

    by_housekeeper = []
    for hk_id, name in roster:
        t = totals.get(hk_id, {})
        worked = t.get("shifts_worked", 0)
        all_done = t.get("shifts_all_done", 0)
        by_housekeeper.append(
            HousekeeperEfficiency(
                housekeeper_id=hk_id,
                name=name,
                shifts_worked=worked,
                shifts_all_done=all_done,
                efficiency_pct=_pct(all_done, worked),
            )
        )
    return EfficiencyResponse(
        from_date=frm, to_date=to, by_housekeeper=by_housekeeper
    )


@router.get("/task-load", response_model=TaskLoadResponse)
async def task_load(
    hotel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
) -> TaskLoadResponse:
    """Per housekeeper: tasks assigned/completed and utilization; plus the
    hotel-wide utilization (are more or fewer housekeepers needed?)."""
    require_same_hotel(hotel_id, current_user)
    frm, to = _resolve_window(date_from, date_to)
    roster = await _housekeepers(db, hotel_id)
    totals = await _daily_totals(db, hotel_id, frm, to)

    by_housekeeper = []
    hotel_clean = 0
    hotel_shift = 0
    for hk_id, name in roster:
        t = totals.get(hk_id, {})
        clean = t.get("clean_seconds_total", 0)
        shift = t.get("shift_seconds_total", 0)
        hotel_clean += clean
        hotel_shift += shift
        by_housekeeper.append(
            HousekeeperLoad(
                housekeeper_id=hk_id,
                name=name,
                tasks_assigned=t.get("tasks_assigned", 0),
                tasks_completed=t.get("tasks_completed", 0),
                clean_seconds_total=clean,
                shift_seconds_total=shift,
                utilization_pct=_pct(clean, shift),
            )
        )
    return TaskLoadResponse(
        from_date=frm,
        to_date=to,
        by_housekeeper=by_housekeeper,
        hotel_clean_seconds_total=hotel_clean,
        hotel_shift_seconds_total=hotel_shift,
        hotel_utilization_pct=_pct(hotel_clean, hotel_shift),
    )
