from conftest import auth_headers


async def test_admin_creates_user(client, admin_user, test_hotel):
    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/users",
        headers=auth_headers(admin_user),
        json={
            "email": "new@test.com",
            "password": "password123",
            "name": "New User",
            "role": "housekeeper",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "new@test.com"
    assert body["role"] == "housekeeper"
    assert "password" not in body and "password_hash" not in body
    # New accounts must set their own password on first login.
    assert body["must_change_password"] is True


async def test_manager_cannot_create_user(client, manager_user, test_hotel):
    """Creating users is admin-only; managers may only view staff."""
    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/users",
        headers=auth_headers(manager_user),
        json={
            "email": "m-created@test.com",
            "password": "password123",
            "name": "Created",
            "role": "housekeeper",
        },
    )
    assert r.status_code == 403


async def test_manager_can_list_users(client, manager_user, test_hotel):
    r = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/users",
        headers=auth_headers(manager_user),
    )
    assert r.status_code == 200


async def test_manager_cannot_delete_user(
    client, manager_user, housekeeper_user, test_hotel
):
    r = await client.delete(
        f"/api/v1/hotels/{test_hotel.id}/users/{housekeeper_user.id}",
        headers=auth_headers(manager_user),
    )
    assert r.status_code == 403


async def test_cannot_change_own_role(client, admin_user, test_hotel):
    r = await client.put(
        f"/api/v1/hotels/{test_hotel.id}/users/{admin_user.id}",
        headers=auth_headers(admin_user),
        json={"role": "housekeeper"},
    )
    assert r.status_code == 403


async def test_cannot_delete_self(client, admin_user, test_hotel):
    r = await client.delete(
        f"/api/v1/hotels/{test_hotel.id}/users/{admin_user.id}",
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 403


async def test_housekeeper_cannot_create_user(client, housekeeper_user, test_hotel):
    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/users",
        headers=auth_headers(housekeeper_user),
        json={
            "email": "x@test.com",
            "password": "password123",
            "name": "X",
            "role": "housekeeper",
        },
    )
    assert r.status_code == 403


async def test_duplicate_email_conflict(client, admin_user, test_hotel):
    r = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/users",
        headers=auth_headers(admin_user),
        json={
            "email": "admin@test.com",  # already exists (admin_user)
            "password": "password123",
            "name": "Dup",
            "role": "manager",
        },
    )
    assert r.status_code == 409


async def test_list_users(client, admin_user, manager_user, test_hotel):
    r = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/users",
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 200
    emails = {u["email"] for u in r.json()}
    assert {"admin@test.com", "manager@test.com"} <= emails


async def test_get_user(client, admin_user, housekeeper_user, test_hotel):
    r = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/users/{housekeeper_user.id}",
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 200
    assert r.json()["id"] == str(housekeeper_user.id)


async def test_update_user(client, admin_user, housekeeper_user, test_hotel):
    r = await client.put(
        f"/api/v1/hotels/{test_hotel.id}/users/{housekeeper_user.id}",
        headers=auth_headers(admin_user),
        json={"name": "Renamed", "role": "manager"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed"
    assert r.json()["role"] == "manager"


async def test_update_user_password_allows_relogin(
    client, admin_user, housekeeper_user, test_hotel
):
    r = await client.put(
        f"/api/v1/hotels/{test_hotel.id}/users/{housekeeper_user.id}",
        headers=auth_headers(admin_user),
        json={"password": "newpassword1"},
    )
    assert r.status_code == 200
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "housekeeper@test.com", "password": "newpassword1"},
    )
    assert login.status_code == 200


async def test_delete_user(client, admin_user, housekeeper_user, test_hotel):
    r = await client.delete(
        f"/api/v1/hotels/{test_hotel.id}/users/{housekeeper_user.id}",
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 204
    follow = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/users/{housekeeper_user.id}",
        headers=auth_headers(admin_user),
    )
    assert follow.status_code == 404
