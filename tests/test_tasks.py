import uuid

from conftest import auth_headers


async def test_create_task(client, manager_user, test_hotel, test_room):
    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/tasks",
        headers=auth_headers(manager_user),
        json={"room_id": str(test_room.id), "priority": "urgent"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "pending"  # unassigned stays pending
    assert body["priority"] == "urgent"


async def test_create_task_with_assignee_auto_assigns(
    client, manager_user, test_hotel, test_room, housekeeper_user
):
    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/tasks",
        headers=auth_headers(manager_user),
        json={
            "room_id": str(test_room.id),
            "assigned_to": str(housekeeper_user.id),
        },
    )
    assert r.status_code == 201
    assert r.json()["status"] == "assigned"


async def test_create_task_bad_room(client, manager_user, test_hotel):
    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/tasks",
        headers=auth_headers(manager_user),
        json={"room_id": str(uuid.uuid4())},
    )
    assert r.status_code == 400


async def test_create_task_assignee_from_other_hotel(
    client, manager_user, test_hotel, test_room, other_admin
):
    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/tasks",
        headers=auth_headers(manager_user),
        json={
            "room_id": str(test_room.id),
            "assigned_to": str(other_admin.id),  # belongs to other_hotel
        },
    )
    assert r.status_code == 400


async def test_housekeeper_cannot_create_task(
    client, housekeeper_user, test_hotel, test_room
):
    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/tasks",
        headers=auth_headers(housekeeper_user),
        json={"room_id": str(test_room.id)},
    )
    assert r.status_code == 403


async def test_list_and_filter_tasks(
    client, manager_user, test_hotel, test_task, housekeeper_user
):
    all_tasks = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/tasks",
        headers=auth_headers(manager_user),
    )
    assert all_tasks.status_code == 200
    assert any(t["id"] == str(test_task.id) for t in all_tasks.json())

    by_status = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/tasks?status=assigned",
        headers=auth_headers(manager_user),
    )
    assert all(t["status"] == "assigned" for t in by_status.json())

    by_assignee = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/tasks?assigned_to={housekeeper_user.id}",
        headers=auth_headers(manager_user),
    )
    assert all(t["assigned_to"] == str(housekeeper_user.id) for t in by_assignee.json())


async def test_assignee_completes_task_marks_room_clean(
    client, housekeeper_user, test_hotel, test_room, test_task
):
    r = await client.patch(
        f"/api/v1/hotels/{test_hotel.id}/tasks/{test_task.id}/status",
        headers=auth_headers(housekeeper_user),
        json={"status": "completed"},
    )
    assert r.status_code == 200
    assert r.json()["completed_at"] is not None

    room = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/rooms/{test_room.id}",
        headers=auth_headers(housekeeper_user),
    )
    assert room.json()["status"] == "clean"


async def test_non_assignee_housekeeper_cannot_update_status(
    client, db_session, test_hotel, test_room, test_task
):
    from app.models.enums import UserRole
    from app.models.user import User

    other_hk = User(
        hotel_id=test_hotel.id,
        email="other-hk@test.com",
        password_hash="x",
        name="Other HK",
        role=UserRole.HOUSEKEEPER,
    )
    db_session.add(other_hk)
    await db_session.flush()

    r = await client.patch(
        f"/api/v1/hotels/{test_hotel.id}/tasks/{test_task.id}/status",
        headers=auth_headers(other_hk),
        json={"status": "in_progress"},
    )
    assert r.status_code == 403


async def test_manager_updates_task(
    client, manager_user, test_hotel, test_task
):
    r = await client.put(
        f"/api/v1/hotels/{test_hotel.id}/tasks/{test_task.id}",
        headers=auth_headers(manager_user),
        json={"priority": "urgent", "notes": "handle first"},
    )
    assert r.status_code == 200
    assert r.json()["priority"] == "urgent"
    assert r.json()["notes"] == "handle first"
