"""Read side of the stats dashboard: RBAC, the aggregation math over the daily
rollups, and date-window filtering. Rollup rows are seeded directly so the math
is asserted in isolation from the recording paths (covered in
test_stats_recording.py).
"""

from datetime import date

from conftest import auth_headers

from app.models.enums import TaskPriority, TaskStatus
from app.models.stats import HousekeeperDailyStats, HousekeeperRoomTypeDailyStats
from app.models.task import Task

D1 = date(2026, 8, 5)
D2 = date(2026, 8, 6)


def _url(hotel, path: str) -> str:
    return f"/api/v1/hotels/{hotel.id}/stats{path}"


async def _seed_daily(db, hotel, hk, d, **kw) -> None:
    db.add(
        HousekeeperDailyStats(
            hotel_id=hotel.id, housekeeper_id=hk.id, stat_date=d, **kw
        )
    )
    await db.flush()


async def _seed_roomtype(db, hotel, hk, d, room_type, secs, count) -> None:
    db.add(
        HousekeeperRoomTypeDailyStats(
            hotel_id=hotel.id,
            housekeeper_id=hk.id,
            stat_date=d,
            room_type=room_type,
            clean_seconds_total=secs,
            clean_count=count,
        )
    )
    await db.flush()


def _find(rows, hk_id):
    return next(r for r in rows if r["housekeeper_id"] == str(hk_id))


# --- RBAC -----------------------------------------------------------------


async def test_stats_forbidden_for_housekeeper(
    client, test_hotel, housekeeper_user
):
    for path in ("/clean-times", "/efficiency", "/task-load"):
        r = await client.get(
            _url(test_hotel, path), headers=auth_headers(housekeeper_user)
        )
        assert r.status_code == 403


async def test_front_desk_can_read_stats(client, test_hotel, front_desk_user):
    r = await client.get(
        _url(test_hotel, "/task-load"), headers=auth_headers(front_desk_user)
    )
    assert r.status_code == 200


# --- task-load ------------------------------------------------------------


async def test_task_load_aggregates_and_utilization(
    client, db_session, test_hotel, housekeeper_user, manager_user
):
    await _seed_daily(
        db_session, test_hotel, housekeeper_user, D1,
        tasks_assigned=3, tasks_completed=2,
        clean_seconds_total=1800, shift_seconds_total=3600,
    )
    await _seed_daily(
        db_session, test_hotel, housekeeper_user, D2,
        tasks_assigned=1, tasks_completed=1,
        clean_seconds_total=900, shift_seconds_total=3600,
    )

    r = await client.get(
        _url(test_hotel, "/task-load?from=2026-08-05&to=2026-08-06"),
        headers=auth_headers(manager_user),
    )
    assert r.status_code == 200
    body = r.json()
    hk = _find(body["by_housekeeper"], housekeeper_user.id)
    assert hk["tasks_completed"] == 3
    assert hk["clean_seconds_total"] == 2700
    assert hk["shift_seconds_total"] == 7200
    assert hk["utilization_pct"] == 37.5  # 2700 / 7200
    assert body["hotel_clean_seconds_total"] == 2700
    assert body["hotel_shift_seconds_total"] == 7200
    assert body["hotel_utilization_pct"] == 37.5


async def test_task_load_null_utilization_without_shift_time(
    client, db_session, test_hotel, housekeeper_user, manager_user
):
    await _seed_daily(
        db_session, test_hotel, housekeeper_user, D1,
        tasks_assigned=2, tasks_completed=0,
        clean_seconds_total=0, shift_seconds_total=0,
    )
    r = await client.get(
        _url(test_hotel, "/task-load?from=2026-08-05&to=2026-08-05"),
        headers=auth_headers(manager_user),
    )
    hk = _find(r.json()["by_housekeeper"], housekeeper_user.id)
    assert hk["utilization_pct"] is None


# --- efficiency -----------------------------------------------------------


async def test_efficiency_ratio(
    client, db_session, test_hotel, housekeeper_user, manager_user
):
    await _seed_daily(
        db_session, test_hotel, housekeeper_user, D1,
        shifts_count=2, shifts_worked=2, shifts_all_done=1,
    )
    await _seed_daily(
        db_session, test_hotel, housekeeper_user, D2,
        shifts_count=1, shifts_worked=1, shifts_all_done=1,
    )
    r = await client.get(
        _url(test_hotel, "/efficiency?from=2026-08-05&to=2026-08-06"),
        headers=auth_headers(manager_user),
    )
    hk = _find(r.json()["by_housekeeper"], housekeeper_user.id)
    assert hk["shifts_worked"] == 3
    assert hk["shifts_all_done"] == 2
    assert abs(hk["efficiency_pct"] - (200 / 3)) < 1e-6


async def test_efficiency_null_without_worked_shifts(
    client, test_hotel, housekeeper_user, manager_user
):
    r = await client.get(
        _url(test_hotel, "/efficiency"), headers=auth_headers(manager_user)
    )
    hk = _find(r.json()["by_housekeeper"], housekeeper_user.id)
    assert hk["shifts_worked"] == 0
    assert hk["efficiency_pct"] is None


# --- clean-times ----------------------------------------------------------


async def test_clean_times_by_room_type(
    client, db_session, test_hotel, housekeeper_user, manager_user
):
    await _seed_roomtype(db_session, test_hotel, housekeeper_user, D1, "STD", 1200, 2)
    await _seed_roomtype(db_session, test_hotel, housekeeper_user, D1, "DLX", 1800, 1)

    r = await client.get(
        _url(test_hotel, "/clean-times?from=2026-08-05&to=2026-08-05"),
        headers=auth_headers(manager_user),
    )
    body = r.json()
    hotel = {x["room_type"]: x for x in body["hotel_by_room_type"]}
    assert hotel["STD"]["avg_seconds"] == 600  # 1200 / 2
    assert hotel["STD"]["clean_count"] == 2
    assert hotel["DLX"]["avg_seconds"] == 1800

    hk = _find(body["by_housekeeper"], housekeeper_user.id)
    by_type = {x["room_type"]: x for x in hk["by_room_type"]}
    assert by_type["STD"]["avg_seconds"] == 600
    assert by_type["DLX"]["avg_seconds"] == 1800


# --- window filtering ------------------------------------------------------


async def test_window_excludes_out_of_range_rows(
    client, db_session, test_hotel, housekeeper_user, manager_user
):
    await _seed_daily(
        db_session, test_hotel, housekeeper_user, date(2026, 7, 1),
        tasks_completed=99,
    )
    await _seed_daily(
        db_session, test_hotel, housekeeper_user, D1, tasks_completed=2,
    )
    r = await client.get(
        _url(test_hotel, "/task-load?from=2026-08-01&to=2026-08-31"),
        headers=auth_headers(manager_user),
    )
    hk = _find(r.json()["by_housekeeper"], housekeeper_user.id)
    assert hk["tasks_completed"] == 2


async def test_task_load_open_tasks_are_live_not_cumulative(
    client, db_session, test_hotel, test_room, housekeeper_user, manager_user
):
    # Live board: two open tasks + one completed. open_tasks must reflect current
    # open work only — not completed tasks, and not any historical rollup counts.
    for status in (
        TaskStatus.ASSIGNED,
        TaskStatus.IN_PROGRESS,
        TaskStatus.COMPLETED,
    ):
        db_session.add(
            Task(
                hotel_id=test_hotel.id,
                room_id=test_room.id,
                assigned_to=housekeeper_user.id,
                status=status,
                priority=TaskPriority.NORMAL,
            )
        )
    await db_session.flush()

    r = await client.get(
        _url(test_hotel, "/task-load"), headers=auth_headers(manager_user)
    )
    hk = _find(r.json()["by_housekeeper"], housekeeper_user.id)
    assert hk["open_tasks"] == 2
