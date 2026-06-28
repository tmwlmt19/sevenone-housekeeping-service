from conftest import auth_headers


async def test_manager_creates_room(client, manager_user, test_hotel):
    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/rooms",
        headers=auth_headers(manager_user),
        json={"room_number": "201", "floor": 2, "room_type": "ste"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["room_number"] == "201"
    assert body["room_type"] == "STE"  # normalized to uppercase
    assert body["status"] == "clean"  # default


async def test_housekeeper_cannot_create_room(client, housekeeper_user, test_hotel):
    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/rooms",
        headers=auth_headers(housekeeper_user),
        json={"room_number": "202"},
    )
    assert r.status_code == 403


async def test_duplicate_room_number_conflict(
    client, manager_user, test_hotel, test_room
):
    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/rooms",
        headers=auth_headers(manager_user),
        json={"room_number": "101"},  # test_room already uses 101
    )
    assert r.status_code == 409


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


async def test_update_room_status(client, manager_user, test_hotel, test_room):
    r = await client.put(
        f"/api/v1/hotels/{test_hotel.id}/rooms/{test_room.id}",
        headers=auth_headers(manager_user),
        json={"status": "out_of_service"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "out_of_service"


async def test_delete_room(client, manager_user, test_hotel, test_room):
    r = await client.delete(
        f"/api/v1/hotels/{test_hotel.id}/rooms/{test_room.id}",
        headers=auth_headers(manager_user),
    )
    assert r.status_code == 204


async def test_get_missing_room_404(client, manager_user, test_hotel):
    import uuid

    r = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/rooms/{uuid.uuid4()}",
        headers=auth_headers(manager_user),
    )
    assert r.status_code == 404
