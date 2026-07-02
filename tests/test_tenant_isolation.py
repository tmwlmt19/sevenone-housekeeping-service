"""Cross-tenant access rules.

Hotel-scoped users (managers/housekeepers) may not read or write another hotel's
resources; the API returns 404 to avoid leaking existence. Admins are
platform-level and may act across all hotels.
"""

from conftest import auth_headers


async def test_cannot_read_other_hotel(client, manager_user, other_hotel):
    r = await client.get(
        f"/api/v1/hotels/{other_hotel.id}", headers=auth_headers(manager_user)
    )
    assert r.status_code == 404


async def test_cannot_list_other_hotel_users(client, manager_user, other_hotel):
    r = await client.get(
        f"/api/v1/hotels/{other_hotel.id}/users",
        headers=auth_headers(manager_user),
    )
    assert r.status_code == 404


async def test_cannot_list_other_hotel_rooms(client, manager_user, other_hotel):
    r = await client.get(
        f"/api/v1/hotels/{other_hotel.id}/rooms",
        headers=auth_headers(manager_user),
    )
    assert r.status_code == 404


async def test_cannot_create_room_in_other_hotel(
    client, manager_user, other_hotel
):
    r = await client.post(
        f"/api/v1/hotels/{other_hotel.id}/rooms",
        headers=auth_headers(manager_user),
        json={"room_number": "999"},
    )
    assert r.status_code == 404


async def test_cannot_read_other_hotel_tasks(client, manager_user, other_hotel):
    r = await client.get(
        f"/api/v1/hotels/{other_hotel.id}/tasks",
        headers=auth_headers(manager_user),
    )
    assert r.status_code == 404


async def test_admin_can_read_other_hotel(client, admin_user, other_hotel):
    """Admins are platform-level and cross-tenant."""
    r = await client.get(
        f"/api/v1/hotels/{other_hotel.id}", headers=auth_headers(admin_user)
    )
    assert r.status_code == 200


async def test_admin_can_list_other_hotel_rooms(client, admin_user, other_hotel):
    r = await client.get(
        f"/api/v1/hotels/{other_hotel.id}/rooms",
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 200
