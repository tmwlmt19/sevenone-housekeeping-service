"""Task approval flow: housekeeper 'done' -> pending_approval -> manager/
front-desk sign-off -> completed (room clean + last_cleaned_by), with a per-hotel
auto-approve shortcut.
"""

from conftest import auth_headers

from app.models.enums import UserRole
from app.models.user import User


def _patch_status(client, hotel, task, user, status):
    return client.patch(
        f"/api/v1/hotels/{hotel.id}/tasks/{task.id}/status",
        headers=auth_headers(user),
        json={"status": status},
    )


async def _get_room(client, hotel, user, room_id):
    r = await client.get(
        f"/api/v1/hotels/{hotel.id}/rooms/{room_id}", headers=auth_headers(user)
    )
    return r.json()


async def _front_desk(db, hotel):
    user = User(
        hotel_id=hotel.id,
        email="frontdesk@test.com",
        password_hash="x",
        name="Front Desk",
        role=UserRole.FRONT_DESK,
    )
    db.add(user)
    await db.flush()
    return user


# --- Housekeeper completion routes through approval ------------------------


async def test_housekeeper_complete_goes_to_pending_approval(
    client, test_hotel, test_room, test_task, housekeeper_user, manager_user
):
    # Default hotel: auto_approve_tasks is false.
    r = await _patch_status(client, test_hotel, test_task, housekeeper_user, "completed")
    assert r.status_code == 200
    assert r.json()["status"] == "pending_approval"
    assert r.json()["completed_at"] is None

    room = await _get_room(client, test_hotel, manager_user, str(test_room.id))
    assert room["status"] == "dirty"  # not cleaned until approved
    assert room["last_cleaned_by"] is None


async def test_housekeeper_complete_auto_approves_when_enabled(
    client, db_session, test_hotel, test_room, test_task, housekeeper_user, manager_user
):
    test_hotel.auto_approve_tasks = True
    await db_session.flush()

    r = await _patch_status(client, test_hotel, test_task, housekeeper_user, "completed")
    assert r.status_code == 200
    assert r.json()["status"] == "completed"

    room = await _get_room(client, test_hotel, manager_user, str(test_room.id))
    assert room["status"] == "clean"
    assert room["last_cleaned_by"] == str(housekeeper_user.id)


# --- Manager / front-desk sign-off -----------------------------------------


async def test_manager_approves_pending_approval(
    client, test_hotel, test_room, test_task, housekeeper_user, manager_user
):
    await _patch_status(client, test_hotel, test_task, housekeeper_user, "completed")

    r = await _patch_status(client, test_hotel, test_task, manager_user, "completed")
    assert r.status_code == 200
    assert r.json()["status"] == "completed"

    room = await _get_room(client, test_hotel, manager_user, str(test_room.id))
    assert room["status"] == "clean"
    # Credited to the housekeeper who did the work, not the approver.
    assert room["last_cleaned_by"] == str(housekeeper_user.id)


async def test_manager_rejects_back_to_assigned(
    client, test_hotel, test_room, test_task, housekeeper_user, manager_user
):
    await _patch_status(client, test_hotel, test_task, housekeeper_user, "completed")

    r = await _patch_status(client, test_hotel, test_task, manager_user, "assigned")
    assert r.status_code == 200
    assert r.json()["status"] == "assigned"
    assert r.json()["completed_at"] is None

    room = await _get_room(client, test_hotel, manager_user, str(test_room.id))
    assert room["status"] == "dirty"


async def test_front_desk_can_approve(
    client, db_session, test_hotel, test_room, test_task, housekeeper_user
):
    front_desk = await _front_desk(db_session, test_hotel)
    await _patch_status(client, test_hotel, test_task, housekeeper_user, "completed")

    r = await _patch_status(client, test_hotel, test_task, front_desk, "completed")
    assert r.status_code == 200
    assert r.json()["status"] == "completed"


async def test_manager_direct_complete_credits_assignee(
    client, test_hotel, test_room, test_task, housekeeper_user, manager_user
):
    # A manager completing an assigned task directly still credits the assignee.
    r = await _patch_status(client, test_hotel, test_task, manager_user, "completed")
    assert r.status_code == 200
    assert r.json()["status"] == "completed"

    room = await _get_room(client, test_hotel, manager_user, str(test_room.id))
    assert room["last_cleaned_by"] == str(housekeeper_user.id)


# --- Housekeeper can't pull back a submitted task --------------------------


async def test_housekeeper_cannot_touch_pending_approval(
    client, test_hotel, test_task, housekeeper_user
):
    await _patch_status(client, test_hotel, test_task, housekeeper_user, "completed")

    r = await _patch_status(
        client, test_hotel, test_task, housekeeper_user, "in_progress"
    )
    assert r.status_code == 403


# --- Auto-approve toggle (hotel ops own it) --------------------------------


async def test_manager_can_toggle_auto_approve(client, test_hotel, manager_user):
    r = await client.patch(
        f"/api/v1/hotels/{test_hotel.id}/task-approval",
        headers=auth_headers(manager_user),
        json={"auto_approve_tasks": True},
    )
    assert r.status_code == 200
    assert r.json()["auto_approve_tasks"] is True


async def test_housekeeper_cannot_toggle_auto_approve(
    client, test_hotel, housekeeper_user
):
    r = await client.patch(
        f"/api/v1/hotels/{test_hotel.id}/task-approval",
        headers=auth_headers(housekeeper_user),
        json={"auto_approve_tasks": True},
    )
    assert r.status_code == 403
