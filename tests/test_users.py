from conftest import auth_headers

# Staff create/delete is no longer exposed directly — admins add/remove staff
# only by approving a manager's access request (see test_access_requests.py).
# These tests cover what remains here: list / get / edit, plus a guard that the
# old direct create/delete routes are gone.


async def test_direct_create_route_removed(client, admin_user, test_hotel):
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
    # Route only supports GET now; POST is not allowed.
    assert r.status_code == 405


async def test_direct_delete_route_removed(
    client, admin_user, housekeeper_user, test_hotel
):
    r = await client.delete(
        f"/api/v1/hotels/{test_hotel.id}/users/{housekeeper_user.id}",
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 405


async def test_manager_can_list_users(client, manager_user, test_hotel):
    r = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/users",
        headers=auth_headers(manager_user),
    )
    assert r.status_code == 200


async def test_cannot_change_own_role(client, admin_user, test_hotel):
    r = await client.put(
        f"/api/v1/hotels/{test_hotel.id}/users/{admin_user.id}",
        headers=auth_headers(admin_user),
        json={"role": "housekeeper"},
    )
    assert r.status_code == 403


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


async def test_manager_cannot_update_user(
    client, manager_user, housekeeper_user, test_hotel
):
    """Editing staff is still admin-only."""
    r = await client.put(
        f"/api/v1/hotels/{test_hotel.id}/users/{housekeeper_user.id}",
        headers=auth_headers(manager_user),
        json={"name": "Nope"},
    )
    assert r.status_code == 403
