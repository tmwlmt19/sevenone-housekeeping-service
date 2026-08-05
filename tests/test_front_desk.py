from conftest import auth_headers

# The front-desk role has the same hotel-ops powers as a manager (room status,
# task CRUD, viewing staff/hotel, toggling auto-approve) but CANNOT file or
# track staff/room access requests. It is hotel-scoped like a manager.


# --------------------------------------------------------------------------- #
# Front desk has manager-level operational powers
# --------------------------------------------------------------------------- #


async def test_front_desk_updates_room_status(
    client, front_desk_user, test_hotel, test_room
):
    r = await client.patch(
        f"/api/v1/hotels/{test_hotel.id}/rooms/{test_room.id}/status",
        headers=auth_headers(front_desk_user),
        json={"status": "out_of_service"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "out_of_service"


async def test_front_desk_creates_task(
    client, front_desk_user, test_hotel, test_room
):
    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/tasks",
        headers=auth_headers(front_desk_user),
        json={"room_id": str(test_room.id), "priority": "urgent"},
    )
    assert r.status_code == 201


async def test_front_desk_lists_staff(client, front_desk_user, test_hotel):
    r = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/users",
        headers=auth_headers(front_desk_user),
    )
    assert r.status_code == 200


async def test_front_desk_views_hotel(client, front_desk_user, test_hotel):
    r = await client.get(
        f"/api/v1/hotels/{test_hotel.id}",
        headers=auth_headers(front_desk_user),
    )
    assert r.status_code == 200


async def test_front_desk_toggles_task_approval(
    client, front_desk_user, test_hotel
):
    r = await client.patch(
        f"/api/v1/hotels/{test_hotel.id}/task-approval",
        headers=auth_headers(front_desk_user),
        json={"auto_approve_tasks": True},
    )
    assert r.status_code == 200
    assert r.json()["auto_approve_tasks"] is True


# --------------------------------------------------------------------------- #
# Front desk CANNOT touch the access-request workflow
# --------------------------------------------------------------------------- #


async def test_front_desk_cannot_file_access_request(
    client, front_desk_user, test_hotel
):
    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/access-requests",
        headers=auth_headers(front_desk_user),
        json={
            "resource": "room",
            "kind": "add",
            "payload": {"room_number": "410", "room_type": "std"},
        },
    )
    assert r.status_code == 403


async def test_front_desk_cannot_list_access_requests(
    client, front_desk_user, test_hotel
):
    r = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/access-requests",
        headers=auth_headers(front_desk_user),
    )
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# Front desk is a creatable role
# --------------------------------------------------------------------------- #


async def test_manager_can_request_adding_front_desk(
    client, manager_user, test_hotel
):
    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/access-requests",
        headers=auth_headers(manager_user),
        json={
            "resource": "staff",
            "kind": "add",
            "payload": {
                "email": "newfd@test.com",
                "name": "Dana Desk",
                "role": "front_desk",
            },
        },
    )
    assert r.status_code == 201
    assert r.json()["payload"]["role"] == "front_desk"
