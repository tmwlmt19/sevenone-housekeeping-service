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


async def test_service_admin_has_no_hotel(client, service_admin):
    """A hotel-less admin logs in and /auth/me reports a null hotel_id."""
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "service-admin@test.com", "password": "password123"},
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["hotel_id"] is None


async def test_service_admin_can_manage_hotels(client, service_admin):
    """A cross-tenant admin can list and create hotels without a hotel of its own."""
    created = await client.post(
        "/api/v1/hotels",
        headers=auth_headers(service_admin),
        json={"name": "Admin-Made Hotel"},
    )
    assert created.status_code == 201
    listing = await client.get(
        "/api/v1/hotels", headers=auth_headers(service_admin)
    )
    assert listing.status_code == 200
    assert any(h["name"] == "Admin-Made Hotel" for h in listing.json())


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
