"""Clear (soft-archive) completed tasks off the board.

Clearing sets archived_at so completed tasks vanish from the default task list
but the rows are kept (history + 'last cleaned by' survive). Manager/front-desk
action; open tasks and other hotels are never touched.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TaskPriority, TaskStatus, UserRole
from app.models.room import Room
from app.models.task import Task
from conftest import _make_user, auth_headers


async def _room(db: AsyncSession, hotel_id: uuid.UUID) -> Room:
    room = Room(hotel_id=hotel_id, room_number="101", status="clean")
    db.add(room)
    await db.flush()
    return room


async def _task(
    db: AsyncSession, hotel_id: uuid.UUID, room_id: uuid.UUID, status: TaskStatus
) -> Task:
    task = Task(
        hotel_id=hotel_id,
        room_id=room_id,
        status=status,
        priority=TaskPriority.NORMAL,
    )
    db.add(task)
    await db.flush()
    return task


async def test_clear_completed_archives_and_hides(
    client, db_session, test_hotel, manager_user
):
    room = await _room(db_session, test_hotel.id)
    await _task(db_session, test_hotel.id, room.id, TaskStatus.COMPLETED)
    await _task(db_session, test_hotel.id, room.id, TaskStatus.COMPLETED)
    await _task(db_session, test_hotel.id, room.id, TaskStatus.ASSIGNED)
    await db_session.commit()

    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/tasks/clear-completed",
        headers=auth_headers(manager_user),
    )
    assert r.status_code == 200
    assert r.json()["cleared"] == 2

    # The board (default list) now shows only the still-open task.
    listing = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/tasks",
        headers=auth_headers(manager_user),
    )
    statuses = [t["status"] for t in listing.json()]
    assert statuses == ["assigned"]

    # The completed rows still exist (soft-archived), not deleted.
    result = await db_session.execute(
        select(Task).where(
            Task.hotel_id == test_hotel.id,
            Task.status == TaskStatus.COMPLETED,
        )
    )
    archived = list(result.scalars().all())
    assert len(archived) == 2
    assert all(t.archived_at is not None for t in archived)


async def test_clear_completed_is_idempotent(
    client, db_session, test_hotel, manager_user
):
    room = await _room(db_session, test_hotel.id)
    await _task(db_session, test_hotel.id, room.id, TaskStatus.COMPLETED)
    await db_session.commit()

    first = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/tasks/clear-completed",
        headers=auth_headers(manager_user),
    )
    assert first.json()["cleared"] == 1
    # A second call finds nothing left to clear.
    second = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/tasks/clear-completed",
        headers=auth_headers(manager_user),
    )
    assert second.json()["cleared"] == 0


async def test_clear_completed_front_desk_allowed(
    client, db_session, test_hotel, front_desk_user
):
    room = await _room(db_session, test_hotel.id)
    await _task(db_session, test_hotel.id, room.id, TaskStatus.COMPLETED)
    await db_session.commit()
    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/tasks/clear-completed",
        headers=auth_headers(front_desk_user),
    )
    assert r.status_code == 200
    assert r.json()["cleared"] == 1


async def test_clear_completed_housekeeper_forbidden(
    client, test_hotel, housekeeper_user
):
    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/tasks/clear-completed",
        headers=auth_headers(housekeeper_user),
    )
    assert r.status_code == 403


async def test_clear_completed_scoped_to_hotel(
    client, db_session, test_hotel, other_hotel, manager_user
):
    """A manager clearing their hotel never touches another tenant's tasks."""
    my_room = await _room(db_session, test_hotel.id)
    other_room = Room(hotel_id=other_hotel.id, room_number="201", status="clean")
    db_session.add(other_room)
    await db_session.flush()
    await _task(db_session, test_hotel.id, my_room.id, TaskStatus.COMPLETED)
    await _task(db_session, other_hotel.id, other_room.id, TaskStatus.COMPLETED)
    await db_session.commit()

    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/tasks/clear-completed",
        headers=auth_headers(manager_user),
    )
    assert r.json()["cleared"] == 1  # only this hotel's task

    result = await db_session.execute(
        select(Task).where(Task.hotel_id == other_hotel.id)
    )
    other_task = result.scalar_one()
    assert other_task.archived_at is None  # untouched
