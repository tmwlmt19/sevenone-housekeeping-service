"""Data collection behind the stats dashboard: started_at on start (cleared on
reassign), the daily/room-type rollups written when a clean finishes, and the
tasks_assigned counter across the assignment flows.
"""

from sqlalchemy import select

from conftest import auth_headers

from app.auth import hash_password
from app.models.enums import UserRole
from app.models.stats import HousekeeperDailyStats, HousekeeperRoomTypeDailyStats
from app.models.task import Task
from app.models.user import User


def _status_url(hotel, task) -> str:
    return f"/api/v1/hotels/{hotel.id}/tasks/{task.id}/status"


async def _add_housekeeper(db, hotel, email: str) -> User:
    user = User(
        hotel_id=hotel.id,
        email=email,
        password_hash=hash_password("password123"),
        name=email.split("@")[0],
        role=UserRole.HOUSEKEEPER,
    )
    db.add(user)
    await db.flush()
    return user


async def _daily(db, housekeeper_id) -> HousekeeperDailyStats | None:
    return (
        await db.execute(
            select(HousekeeperDailyStats).where(
                HousekeeperDailyStats.housekeeper_id == housekeeper_id
            )
        )
    ).scalar_one_or_none()


# --- started_at -----------------------------------------------------------


async def test_started_at_set_on_in_progress(
    client, db_session, test_hotel, test_task, housekeeper_user
):
    r = await client.patch(
        _status_url(test_hotel, test_task),
        headers=auth_headers(housekeeper_user),
        json={"status": "in_progress"},
    )
    assert r.status_code == 200
    assert r.json()["started_at"] is not None

    task = await db_session.get(Task, test_task.id)
    await db_session.refresh(task)
    assert task.started_at is not None


async def test_reassign_clears_started_at_and_counts_new_owner(
    client, db_session, test_hotel, test_task, housekeeper_user, manager_user
):
    hk2 = await _add_housekeeper(db_session, test_hotel, "hk2@test.com")

    await client.patch(
        _status_url(test_hotel, test_task),
        headers=auth_headers(housekeeper_user),
        json={"status": "in_progress"},
    )

    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/tasks/reassign",
        headers=auth_headers(manager_user),
        json={
            "from_housekeeper_id": str(housekeeper_user.id),
            "to_housekeeper_id": str(hk2.id),
        },
    )
    assert r.status_code == 200

    task = await db_session.get(Task, test_task.id)
    await db_session.refresh(task)
    assert task.started_at is None
    assert task.assigned_to == hk2.id

    d = await _daily(db_session, hk2.id)
    assert d is not None and d.tasks_assigned == 1


# --- completion rollups ----------------------------------------------------


async def test_completion_records_daily_and_roomtype(
    client, db_session, test_hotel, test_room, test_task, housekeeper_user
):
    test_hotel.auto_approve_tasks = True
    await db_session.flush()

    await client.patch(
        _status_url(test_hotel, test_task),
        headers=auth_headers(housekeeper_user),
        json={"status": "in_progress"},
    )
    await client.patch(
        _status_url(test_hotel, test_task),
        headers=auth_headers(housekeeper_user),
        json={"status": "completed"},
    )

    d = await _daily(db_session, housekeeper_user.id)
    assert d is not None
    assert d.tasks_completed == 1
    assert d.clean_count == 1
    assert d.clean_seconds_total >= 0

    rt = (
        await db_session.execute(
            select(HousekeeperRoomTypeDailyStats).where(
                HousekeeperRoomTypeDailyStats.housekeeper_id == housekeeper_user.id
            )
        )
    ).scalar_one()
    assert rt.room_type == "STD"  # test_room.room_type
    assert rt.clean_count == 1


async def test_clean_recorded_once_across_approval(
    client, db_session, test_hotel, test_task, housekeeper_user, manager_user
):
    # Default hotel requires approval: housekeeper "complete" -> pending_approval
    # records the clean; the manager's later approval must NOT record it again.
    await client.patch(
        _status_url(test_hotel, test_task),
        headers=auth_headers(housekeeper_user),
        json={"status": "in_progress"},
    )
    await client.patch(
        _status_url(test_hotel, test_task),
        headers=auth_headers(housekeeper_user),
        json={"status": "completed"},
    )

    d = await _daily(db_session, housekeeper_user.id)
    assert d is not None and d.tasks_completed == 1

    await client.patch(
        _status_url(test_hotel, test_task),
        headers=auth_headers(manager_user),
        json={"status": "completed"},
    )

    await db_session.refresh(d)
    assert d.tasks_completed == 1


# --- assignment counting ---------------------------------------------------


async def test_create_with_assignee_counts_assignment(
    client, db_session, test_hotel, test_room, housekeeper_user, manager_user
):
    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/tasks",
        headers=auth_headers(manager_user),
        json={"room_id": str(test_room.id), "assigned_to": str(housekeeper_user.id)},
    )
    assert r.status_code == 201

    d = await _daily(db_session, housekeeper_user.id)
    assert d is not None and d.tasks_assigned == 1


async def test_import_counts_assignments(
    client, db_session, test_hotel, test_room, housekeeper_user, manager_user
):
    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/tasks/import",
        headers=auth_headers(manager_user),
        json={
            "rooms": [test_room.room_number],
            "housekeeper_ids": [str(housekeeper_user.id)],
        },
    )
    assert r.status_code == 201
    assert r.json()["tasks_created"] == 1

    d = await _daily(db_session, housekeeper_user.id)
    assert d is not None and d.tasks_assigned == 1
