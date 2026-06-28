"""Cross-tenant access must be denied. A user from hotel A may not read or
write hotel B's resources; the API returns 404 to avoid leaking existence."""

from conftest import auth_headers


async def test_cannot_read_other_hotel(client, admin_user, other_hotel):
    r = await client.get(
        f"/api/v1/hotels/{other_hotel.id}", headers=auth_headers(admin_user)
    )
    assert r.status_code == 404


async def test_cannot_list_other_hotel_users(client, admin_user, other_hotel):
    r = await client.get(
        f"/api/v1/hotels/{other_hotel.id}/users",
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 404


async def test_cannot_list_other_hotel_rooms(client, admin_user, other_hotel):
    r = await client.get(
        f"/api/v1/hotels/{other_hotel.id}/rooms",
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 404


async def test_cannot_create_room_in_other_hotel(client, admin_user, other_hotel):
    r = await client.post(
        f"/api/v1/hotels/{other_hotel.id}/rooms",
        headers=auth_headers(admin_user),
        json={"room_number": "999"},
    )
    assert r.status_code == 404


async def test_cannot_read_other_hotel_tasks(client, admin_user, other_hotel):
    r = await client.get(
        f"/api/v1/hotels/{other_hotel.id}/tasks",
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 404
