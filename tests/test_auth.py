from conftest import auth_headers


async def test_login_success(client, admin_user):
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.com", "password": "password123"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


async def test_login_wrong_password(client, admin_user):
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.com", "password": "wrong"},
    )
    assert r.status_code == 401


async def test_login_unknown_email(client, admin_user):
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@test.com", "password": "password123"},
    )
    assert r.status_code == 401


async def test_me_with_valid_token(client, admin_user):
    r = await client.get("/api/v1/auth/me", headers=auth_headers(admin_user))
    assert r.status_code == 200
    assert r.json()["email"] == "admin@test.com"
    assert r.json()["role"] == "admin"


async def test_change_password_clears_must_change_flag(
    client, admin_user, test_hotel
):
    # A freshly created account has the forced-change flag set.
    created = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/users",
        headers=auth_headers(admin_user),
        json={
            "email": "firstlogin@test.com",
            "password": "temppass123",
            "name": "First Login",
            "role": "housekeeper",
        },
    )
    assert created.json()["must_change_password"] is True

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "firstlogin@test.com", "password": "temppass123"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    changed = await client.put(
        "/api/v1/auth/me/password",
        headers=headers,
        json={"current_password": "temppass123", "new_password": "chosen-pass1"},
    )
    assert changed.status_code == 204

    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.json()["must_change_password"] is False


async def test_me_without_token(client):
    r = await client.get("/api/v1/auth/me")
    assert r.status_code == 401


async def test_me_with_bad_token(client):
    r = await client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer garbage"}
    )
    assert r.status_code == 401
