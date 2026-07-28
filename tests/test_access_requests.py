import uuid

from conftest import auth_headers

# The manager -> admin approval queue. Managers file add/remove requests for
# staff and rooms; admins approve (which performs the action atomically) or
# reject. Admins have no direct create/delete path anymore.


def _hotel_url(hotel_id) -> str:
    return f"/api/v1/hotels/{hotel_id}/access-requests"


# --------------------------------------------------------------------------- #
# Filing (manager)
# --------------------------------------------------------------------------- #


async def test_manager_files_staff_add(client, manager_user, test_hotel):
    r = await client.post(
        _hotel_url(test_hotel.id),
        headers=auth_headers(manager_user),
        json={
            "resource": "staff",
            "kind": "add",
            "note": "new night cleaner",
            "payload": {
                "email": "cleaner@test.com",
                "name": "Nia Cleaner",
                "role": "housekeeper",
            },
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "pending"
    assert body["resource"] == "staff"
    assert body["kind"] == "add"
    assert body["requested_by"] == str(manager_user.id)
    assert body["payload"]["email"] == "cleaner@test.com"


async def test_manager_files_staff_remove(
    client, manager_user, housekeeper_user, test_hotel
):
    r = await client.post(
        _hotel_url(test_hotel.id),
        headers=auth_headers(manager_user),
        json={
            "resource": "staff",
            "kind": "remove",
            "target_id": str(housekeeper_user.id),
        },
    )
    assert r.status_code == 201
    assert r.json()["target_id"] == str(housekeeper_user.id)


async def test_manager_files_room_add(client, manager_user, test_hotel):
    r = await client.post(
        _hotel_url(test_hotel.id),
        headers=auth_headers(manager_user),
        json={
            "resource": "room",
            "kind": "add",
            "payload": {"room_number": "305", "room_type": "dlx"},
        },
    )
    assert r.status_code == 201
    # room_type normalized to uppercase in the stored payload.
    assert r.json()["payload"]["room_type"] == "DLX"


async def test_housekeeper_cannot_file(client, housekeeper_user, test_hotel):
    r = await client.post(
        _hotel_url(test_hotel.id),
        headers=auth_headers(housekeeper_user),
        json={
            "resource": "staff",
            "kind": "remove",
            "target_id": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 403


async def test_manager_cannot_file_for_other_hotel(
    client, manager_user, other_hotel
):
    r = await client.post(
        _hotel_url(other_hotel.id),
        headers=auth_headers(manager_user),
        json={
            "resource": "staff",
            "kind": "add",
            "payload": {
                "email": "x@test.com",
                "name": "X",
                "role": "housekeeper",
            },
        },
    )
    assert r.status_code == 404


async def test_add_existing_email_conflicts(
    client, manager_user, housekeeper_user, test_hotel
):
    r = await client.post(
        _hotel_url(test_hotel.id),
        headers=auth_headers(manager_user),
        json={
            "resource": "staff",
            "kind": "add",
            "payload": {
                "email": "housekeeper@test.com",  # already exists
                "name": "Dup",
                "role": "housekeeper",
            },
        },
    )
    assert r.status_code == 409


async def test_cannot_request_removing_self(client, manager_user, test_hotel):
    r = await client.post(
        _hotel_url(test_hotel.id),
        headers=auth_headers(manager_user),
        json={
            "resource": "staff",
            "kind": "remove",
            "target_id": str(manager_user.id),
        },
    )
    assert r.status_code == 400


async def test_cannot_request_removing_admin(
    client, manager_user, admin_user, test_hotel
):
    r = await client.post(
        _hotel_url(test_hotel.id),
        headers=auth_headers(manager_user),
        json={
            "resource": "staff",
            "kind": "remove",
            "target_id": str(admin_user.id),
        },
    )
    assert r.status_code == 400


async def test_duplicate_pending_remove_conflicts(
    client, manager_user, housekeeper_user, test_hotel
):
    body = {
        "resource": "staff",
        "kind": "remove",
        "target_id": str(housekeeper_user.id),
    }
    first = await client.post(
        _hotel_url(test_hotel.id), headers=auth_headers(manager_user), json=body
    )
    assert first.status_code == 201
    second = await client.post(
        _hotel_url(test_hotel.id), headers=auth_headers(manager_user), json=body
    )
    assert second.status_code == 409


async def test_duplicate_pending_add_staff_conflicts(
    client, manager_user, test_hotel
):
    body = {
        "resource": "staff",
        "kind": "add",
        "payload": {
            "email": "newhire@test.com",
            "name": "New Hire",
            "role": "housekeeper",
        },
    }
    first = await client.post(
        _hotel_url(test_hotel.id), headers=auth_headers(manager_user), json=body
    )
    assert first.status_code == 201
    second = await client.post(
        _hotel_url(test_hotel.id), headers=auth_headers(manager_user), json=body
    )
    assert second.status_code == 409


async def test_duplicate_pending_add_room_conflicts(
    client, manager_user, test_hotel
):
    body = {
        "resource": "room",
        "kind": "add",
        "payload": {"room_number": "808"},
    }
    first = await client.post(
        _hotel_url(test_hotel.id), headers=auth_headers(manager_user), json=body
    )
    assert first.status_code == 201
    second = await client.post(
        _hotel_url(test_hotel.id), headers=auth_headers(manager_user), json=body
    )
    assert second.status_code == 409


async def test_add_requires_payload(client, manager_user, test_hotel):
    r = await client.post(
        _hotel_url(test_hotel.id),
        headers=auth_headers(manager_user),
        json={"resource": "staff", "kind": "add"},
    )
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# Admin queue + decisions
# --------------------------------------------------------------------------- #


async def _file(client, manager_user, hotel_id, body) -> str:
    r = await client.post(
        _hotel_url(hotel_id), headers=auth_headers(manager_user), json=body
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_manager_cannot_see_global_queue(client, manager_user):
    r = await client.get(
        "/api/v1/access-requests", headers=auth_headers(manager_user)
    )
    assert r.status_code == 403


async def test_admin_sees_pending_queue(
    client, admin_user, manager_user, test_hotel
):
    await _file(
        client,
        manager_user,
        test_hotel.id,
        {
            "resource": "room",
            "kind": "add",
            "payload": {"room_number": "400"},
        },
    )
    r = await client.get(
        "/api/v1/access-requests", headers=auth_headers(admin_user)
    )
    assert r.status_code == 200
    assert len(r.json()) >= 1
    assert all(item["status"] == "pending" for item in r.json())


async def test_approve_staff_add_creates_user(
    client, admin_user, manager_user, test_hotel
):
    req_id = await _file(
        client,
        manager_user,
        test_hotel.id,
        {
            "resource": "staff",
            "kind": "add",
            "payload": {
                "email": "hired@test.com",
                "name": "Hired Person",
                "role": "housekeeper",
            },
        },
    )
    r = await client.post(
        f"/api/v1/access-requests/{req_id}/approve",
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["request"]["status"] == "approved"
    assert body["temporary_password"] is not None

    # The user now exists in the hotel.
    users = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/users",
        headers=auth_headers(admin_user),
    )
    assert "hired@test.com" in {u["email"] for u in users.json()}


async def test_approve_staff_remove_deletes_user(
    client, admin_user, manager_user, housekeeper_user, test_hotel
):
    req_id = await _file(
        client,
        manager_user,
        test_hotel.id,
        {
            "resource": "staff",
            "kind": "remove",
            "target_id": str(housekeeper_user.id),
        },
    )
    r = await client.post(
        f"/api/v1/access-requests/{req_id}/approve",
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 200
    assert r.json()["temporary_password"] is None

    gone = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/users/{housekeeper_user.id}",
        headers=auth_headers(admin_user),
    )
    assert gone.status_code == 404


async def test_approve_room_add_creates_room(
    client, admin_user, manager_user, test_hotel
):
    req_id = await _file(
        client,
        manager_user,
        test_hotel.id,
        {
            "resource": "room",
            "kind": "add",
            "payload": {"room_number": "501", "room_type": "std"},
        },
    )
    r = await client.post(
        f"/api/v1/access-requests/{req_id}/approve",
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 200
    rooms = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/rooms",
        headers=auth_headers(admin_user),
    )
    assert "501" in {room["room_number"] for room in rooms.json()}


async def test_approve_room_remove_deletes_room(
    client, admin_user, manager_user, test_hotel, test_room
):
    req_id = await _file(
        client,
        manager_user,
        test_hotel.id,
        {
            "resource": "room",
            "kind": "remove",
            "target_id": str(test_room.id),
        },
    )
    r = await client.post(
        f"/api/v1/access-requests/{req_id}/approve",
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 200
    gone = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/rooms/{test_room.id}",
        headers=auth_headers(admin_user),
    )
    assert gone.status_code == 404


async def test_double_approve_conflicts(
    client, admin_user, manager_user, test_hotel, test_room
):
    req_id = await _file(
        client,
        manager_user,
        test_hotel.id,
        {
            "resource": "room",
            "kind": "remove",
            "target_id": str(test_room.id),
        },
    )
    first = await client.post(
        f"/api/v1/access-requests/{req_id}/approve",
        headers=auth_headers(admin_user),
    )
    assert first.status_code == 200
    second = await client.post(
        f"/api/v1/access-requests/{req_id}/approve",
        headers=auth_headers(admin_user),
    )
    assert second.status_code == 409


async def test_reject_records_note_and_does_nothing(
    client, admin_user, manager_user, housekeeper_user, test_hotel
):
    req_id = await _file(
        client,
        manager_user,
        test_hotel.id,
        {
            "resource": "staff",
            "kind": "remove",
            "target_id": str(housekeeper_user.id),
        },
    )
    r = await client.post(
        f"/api/v1/access-requests/{req_id}/reject",
        headers=auth_headers(admin_user),
        json={"decision_note": "keep them"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    assert r.json()["decision_note"] == "keep them"

    # The user is untouched.
    still = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/users/{housekeeper_user.id}",
        headers=auth_headers(admin_user),
    )
    assert still.status_code == 200


async def test_manager_lists_own_hotel_requests(
    client, manager_user, test_hotel
):
    await _file(
        client,
        manager_user,
        test_hotel.id,
        {
            "resource": "room",
            "kind": "add",
            "payload": {"room_number": "600"},
        },
    )
    r = await client.get(
        _hotel_url(test_hotel.id), headers=auth_headers(manager_user)
    )
    assert r.status_code == 200
    assert len(r.json()) >= 1


async def test_reject_then_approve_conflicts(
    client, admin_user, manager_user, housekeeper_user, test_hotel
):
    req_id = await _file(
        client,
        manager_user,
        test_hotel.id,
        {
            "resource": "staff",
            "kind": "remove",
            "target_id": str(housekeeper_user.id),
        },
    )
    rej = await client.post(
        f"/api/v1/access-requests/{req_id}/reject",
        headers=auth_headers(admin_user),
        json={"decision_note": "no"},
    )
    assert rej.status_code == 200
    appr = await client.post(
        f"/api/v1/access-requests/{req_id}/approve",
        headers=auth_headers(admin_user),
    )
    assert appr.status_code == 409
