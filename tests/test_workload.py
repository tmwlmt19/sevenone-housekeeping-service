"""Reassign / redistribute a housekeeper's open workload.

- reassign: move ALL of one housekeeper's open tasks to a single other one.
- redistribute: split them evenly across the hotel's other housekeepers,
  balancing by current open load.

Only open tasks (pending/assigned/in_progress) move; completed and
pending_approval tasks stay put. Hotel-ops action (manager/front-desk).
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TaskPriority, TaskStatus, UserRole
from app.models.room import Room
from app.models.task import Task
from app.models.user import User
from conftest import _make_user, auth_headers


async def _room(db: AsyncSession, hotel_id: uuid.UUID, number: str) -> Room:
    room = Room(hotel_id=hotel_id, room_number=number, status="dirty")
    db.add(room)
    await db.flush()
    return room


async def _task(
    db: AsyncSession,
    hotel_id: uuid.UUID,
    room_id: uuid.UUID,
    assignee: uuid.UUID | None,
    status: TaskStatus,
) -> Task:
    task = Task(
        hotel_id=hotel_id,
        room_id=room_id,
        assigned_to=assignee,
        status=status,
        priority=TaskPriority.NORMAL,
    )
    db.add(task)
    await db.flush()
    return task


async def _open_count(db: AsyncSession, assignee: uuid.UUID) -> int:
    result = await db.execute(
        select(Task).where(
            Task.assigned_to == assignee,
            Task.status.in_(
                (TaskStatus.PENDING, TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS)
            ),
        )
    )
    return len(list(result.scalars().all()))


# --------------------------------------------------------------------------- #
# Reassign (call-in): all → one
# --------------------------------------------------------------------------- #


async def test_reassign_moves_all_open_tasks(
    client, db_session, test_hotel, manager_user, housekeeper_user
):
    other = await _make_user(db_session, test_hotel, "hk2@test.com", UserRole.HOUSEKEEPER)
    room = await _room(db_session, test_hotel.id, "101")
    await _task(db_session, test_hotel.id, room.id, housekeeper_user.id, TaskStatus.ASSIGNED)
    await _task(db_session, test_hotel.id, room.id, housekeeper_user.id, TaskStatus.IN_PROGRESS)
    await db_session.commit()

    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/tasks/reassign",
        headers=auth_headers(manager_user),
        json={
            "from_housekeeper_id": str(housekeeper_user.id),
            "to_housekeeper_id": str(other.id),
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tasks_moved"] == 2
    assert body["assignments"] == [
        {"housekeeper_id": str(other.id), "name": other.name, "tasks_assigned": 2}
    ]
    # All moved tasks now belong to `other` and are `assigned` (in_progress reset).
    assert await _open_count(db_session, housekeeper_user.id) == 0
    assert await _open_count(db_session, other.id) == 2


async def test_reassign_leaves_completed_and_pending_approval(
    client, db_session, test_hotel, manager_user, housekeeper_user
):
    other = await _make_user(db_session, test_hotel, "hk2@test.com", UserRole.HOUSEKEEPER)
    room = await _room(db_session, test_hotel.id, "101")
    await _task(db_session, test_hotel.id, room.id, housekeeper_user.id, TaskStatus.ASSIGNED)
    await _task(db_session, test_hotel.id, room.id, housekeeper_user.id, TaskStatus.COMPLETED)
    await _task(db_session, test_hotel.id, room.id, housekeeper_user.id, TaskStatus.PENDING_APPROVAL)
    await db_session.commit()

    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/tasks/reassign",
        headers=auth_headers(manager_user),
        json={
            "from_housekeeper_id": str(housekeeper_user.id),
            "to_housekeeper_id": str(other.id),
        },
    )
    assert r.status_code == 200
    assert r.json()["tasks_moved"] == 1
    assert await _open_count(db_session, other.id) == 1


async def test_reassign_to_same_housekeeper_400(
    client, test_hotel, manager_user, housekeeper_user
):
    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/tasks/reassign",
        headers=auth_headers(manager_user),
        json={
            "from_housekeeper_id": str(housekeeper_user.id),
            "to_housekeeper_id": str(housekeeper_user.id),
        },
    )
    assert r.status_code == 400


async def test_reassign_to_non_housekeeper_400(
    client, test_hotel, manager_user, housekeeper_user
):
    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/tasks/reassign",
        headers=auth_headers(manager_user),
        json={
            "from_housekeeper_id": str(housekeeper_user.id),
            "to_housekeeper_id": str(manager_user.id),  # not a housekeeper
        },
    )
    assert r.status_code == 400


# --------------------------------------------------------------------------- #
# Redistribute (no-show): all → split across the others
# --------------------------------------------------------------------------- #


async def test_redistribute_splits_evenly(
    client, db_session, test_hotel, manager_user, housekeeper_user
):
    b = await _make_user(db_session, test_hotel, "hkB@test.com", UserRole.HOUSEKEEPER)
    c = await _make_user(db_session, test_hotel, "hkC@test.com", UserRole.HOUSEKEEPER)
    room = await _room(db_session, test_hotel.id, "101")
    for _ in range(4):
        await _task(db_session, test_hotel.id, room.id, housekeeper_user.id, TaskStatus.ASSIGNED)
    await db_session.commit()

    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/tasks/redistribute",
        headers=auth_headers(manager_user),
        json={"from_housekeeper_id": str(housekeeper_user.id)},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tasks_moved"] == 4
    assert await _open_count(db_session, housekeeper_user.id) == 0
    # Four tasks split across two idle housekeepers → 2 each.
    by_id = {a["housekeeper_id"]: a["tasks_assigned"] for a in body["assignments"]}
    assert by_id == {str(b.id): 2, str(c.id): 2}


async def test_redistribute_balances_by_existing_load(
    client, db_session, test_hotel, manager_user, housekeeper_user
):
    b = await _make_user(db_session, test_hotel, "hkB@test.com", UserRole.HOUSEKEEPER)
    c = await _make_user(db_session, test_hotel, "hkC@test.com", UserRole.HOUSEKEEPER)
    room = await _room(db_session, test_hotel.id, "101")
    # B already carries 2 open tasks; C is idle.
    for _ in range(2):
        await _task(db_session, test_hotel.id, room.id, b.id, TaskStatus.ASSIGNED)
    # A (housekeeper_user) has 2 to hand off.
    for _ in range(2):
        await _task(db_session, test_hotel.id, room.id, housekeeper_user.id, TaskStatus.ASSIGNED)
    await db_session.commit()

    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/tasks/redistribute",
        headers=auth_headers(manager_user),
        json={"from_housekeeper_id": str(housekeeper_user.id)},
    )
    assert r.status_code == 200
    # Both of A's tasks go to idle C, evening the totals at 2 each.
    assert await _open_count(db_session, b.id) == 2
    assert await _open_count(db_session, c.id) == 2


async def test_redistribute_across_chosen_subset(
    client, db_session, test_hotel, manager_user, housekeeper_user
):
    # Three idle housekeepers available, but the manager only spreads across two.
    b = await _make_user(db_session, test_hotel, "hkB@test.com", UserRole.HOUSEKEEPER)
    c = await _make_user(db_session, test_hotel, "hkC@test.com", UserRole.HOUSEKEEPER)
    d = await _make_user(db_session, test_hotel, "hkD@test.com", UserRole.HOUSEKEEPER)
    room = await _room(db_session, test_hotel.id, "101")
    for _ in range(4):
        await _task(db_session, test_hotel.id, room.id, housekeeper_user.id, TaskStatus.ASSIGNED)
    await db_session.commit()

    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/tasks/redistribute",
        headers=auth_headers(manager_user),
        json={
            "from_housekeeper_id": str(housekeeper_user.id),
            "to_housekeeper_ids": [str(b.id), str(c.id)],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tasks_moved"] == 4
    by_id = {a["housekeeper_id"]: a["tasks_assigned"] for a in body["assignments"]}
    # Only B and C receive work, 2 each; D was not chosen and stays idle.
    assert by_id == {str(b.id): 2, str(c.id): 2}
    assert await _open_count(db_session, d.id) == 0


async def test_redistribute_to_single_target_gets_everything(
    client, db_session, test_hotel, manager_user, housekeeper_user
):
    b = await _make_user(db_session, test_hotel, "hkB@test.com", UserRole.HOUSEKEEPER)
    await _make_user(db_session, test_hotel, "hkC@test.com", UserRole.HOUSEKEEPER)
    room = await _room(db_session, test_hotel.id, "101")
    for _ in range(3):
        await _task(db_session, test_hotel.id, room.id, housekeeper_user.id, TaskStatus.ASSIGNED)
    await db_session.commit()

    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/tasks/redistribute",
        headers=auth_headers(manager_user),
        json={
            "from_housekeeper_id": str(housekeeper_user.id),
            "to_housekeeper_ids": [str(b.id)],
        },
    )
    assert r.status_code == 200
    assert r.json()["tasks_moved"] == 3
    assert await _open_count(db_session, b.id) == 3


async def test_redistribute_subset_including_self_400(
    client, db_session, test_hotel, manager_user, housekeeper_user
):
    b = await _make_user(db_session, test_hotel, "hkB@test.com", UserRole.HOUSEKEEPER)
    await db_session.commit()
    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/tasks/redistribute",
        headers=auth_headers(manager_user),
        json={
            "from_housekeeper_id": str(housekeeper_user.id),
            "to_housekeeper_ids": [str(b.id), str(housekeeper_user.id)],
        },
    )
    assert r.status_code == 400


async def test_redistribute_subset_non_housekeeper_400(
    client, test_hotel, manager_user, housekeeper_user
):
    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/tasks/redistribute",
        headers=auth_headers(manager_user),
        json={
            "from_housekeeper_id": str(housekeeper_user.id),
            "to_housekeeper_ids": [str(manager_user.id)],  # not a housekeeper
        },
    )
    assert r.status_code == 400


async def test_redistribute_no_other_housekeepers_400(
    client, test_hotel, manager_user, housekeeper_user
):
    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/tasks/redistribute",
        headers=auth_headers(manager_user),
        json={"from_housekeeper_id": str(housekeeper_user.id)},
    )
    assert r.status_code == 400


# --------------------------------------------------------------------------- #
# RBAC
# --------------------------------------------------------------------------- #


async def test_front_desk_can_reassign(
    client, db_session, test_hotel, front_desk_user, housekeeper_user
):
    other = await _make_user(db_session, test_hotel, "hk2@test.com", UserRole.HOUSEKEEPER)
    await db_session.commit()
    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/tasks/reassign",
        headers=auth_headers(front_desk_user),
        json={
            "from_housekeeper_id": str(housekeeper_user.id),
            "to_housekeeper_id": str(other.id),
        },
    )
    assert r.status_code == 200


async def test_housekeeper_cannot_redistribute(
    client, test_hotel, housekeeper_user
):
    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/tasks/redistribute",
        headers=auth_headers(housekeeper_user),
        json={"from_housekeeper_id": str(housekeeper_user.id)},
    )
    assert r.status_code == 403
