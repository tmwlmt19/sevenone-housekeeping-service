import uuid

from conftest import auth_headers

# Room create/delete is no longer exposed directly — admins add/remove rooms
# only by approving a manager's access request (see test_access_requests.py).
# These tests cover what remains: list / get, the manager status-only PATCH,
# the admin full-edit PUT, and a guard that the old create/delete routes are gone.


async def test_direct_create_route_removed(client, admin_user, test_hotel):
    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/rooms",
        headers=auth_headers(admin_user),
        json={"room_number": "201", "floor": 2, "room_type": "ste"},
    )
    assert r.status_code == 405


async def test_direct_delete_route_removed(
    client, admin_user, test_hotel, test_room
):
    r = await client.delete(
        f"/api/v1/hotels/{test_hotel.id}/rooms/{test_room.id}",
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 405


async def test_list_and_get_room(client, housekeeper_user, test_hotel, test_room):
    r = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/rooms",
        headers=auth_headers(housekeeper_user),
    )
    assert r.status_code == 200
    assert any(room["id"] == str(test_room.id) for room in r.json())

    one = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/rooms/{test_room.id}",
        headers=auth_headers(housekeeper_user),
    )
    assert one.status_code == 200
    assert one.json()["id"] == str(test_room.id)


async def test_manager_updates_status_via_patch(
    client, manager_user, test_hotel, test_room
):
    r = await client.patch(
        f"/api/v1/hotels/{test_hotel.id}/rooms/{test_room.id}/status",
        headers=auth_headers(manager_user),
        json={"status": "out_of_service"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "out_of_service"


async def test_housekeeper_cannot_update_status(
    client, housekeeper_user, test_hotel, test_room
):
    r = await client.patch(
        f"/api/v1/hotels/{test_hotel.id}/rooms/{test_room.id}/status",
        headers=auth_headers(housekeeper_user),
        json={"status": "clean"},
    )
    assert r.status_code == 403


async def test_manager_cannot_full_update_room(
    client, manager_user, test_hotel, test_room
):
    # The full-edit PUT (rename/floor/type) is admin-only.
    r = await client.put(
        f"/api/v1/hotels/{test_hotel.id}/rooms/{test_room.id}",
        headers=auth_headers(manager_user),
        json={"room_number": "999"},
    )
    assert r.status_code == 403


async def test_admin_full_update_room(client, admin_user, test_hotel, test_room):
    r = await client.put(
        f"/api/v1/hotels/{test_hotel.id}/rooms/{test_room.id}",
        headers=auth_headers(admin_user),
        json={"room_number": "999", "status": "out_of_service"},
    )
    assert r.status_code == 200
    assert r.json()["room_number"] == "999"


async def test_get_missing_room_404(client, manager_user, test_hotel):
    r = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/rooms/{uuid.uuid4()}",
        headers=auth_headers(manager_user),
    )
    assert r.status_code == 404
