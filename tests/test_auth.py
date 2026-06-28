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


async def test_me_without_token(client):
    r = await client.get("/api/v1/auth/me")
    assert r.status_code == 401


async def test_me_with_bad_token(client):
    r = await client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer garbage"}
    )
    assert r.status_code == 401
