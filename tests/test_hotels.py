from conftest import auth_headers


async def test_admin_creates_hotel(client, admin_user):
    r = await client.post(
        "/api/v1/hotels",
        headers=auth_headers(admin_user),
        json={"name": "New Hotel", "address": "123 Main St"},
    )
    assert r.status_code == 201
    assert r.json()["name"] == "New Hotel"


async def test_manager_cannot_create_hotel(client, manager_user):
    r = await client.post(
        "/api/v1/hotels",
        headers=auth_headers(manager_user),
        json={"name": "Nope"},
    )
    assert r.status_code == 403


async def test_get_own_hotel(client, admin_user, test_hotel):
    r = await client.get(
        f"/api/v1/hotels/{test_hotel.id}", headers=auth_headers(admin_user)
    )
    assert r.status_code == 200
    assert r.json()["id"] == str(test_hotel.id)


async def test_update_hotel(client, admin_user, test_hotel):
    r = await client.put(
        f"/api/v1/hotels/{test_hotel.id}",
        headers=auth_headers(admin_user),
        json={"name": "Renamed Hotel"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed Hotel"


async def test_manager_cannot_update_hotel(client, manager_user, test_hotel):
    r = await client.put(
        f"/api/v1/hotels/{test_hotel.id}",
        headers=auth_headers(manager_user),
        json={"name": "Nope"},
    )
    assert r.status_code == 403
