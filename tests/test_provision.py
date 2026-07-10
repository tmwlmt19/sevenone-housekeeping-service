from conftest import auth_headers


def _payload(**overrides):
    body = {
        "hotel": {"name": "Provisioned Inn", "address": "1 Ocean Ave"},
        "rooms": [
            {"room_number": "101", "floor": 1, "room_type": "std"},
            {"room_number": "102", "floor": 1},
        ],
        "users": [
            {"email": "gm@prov.com", "name": "Gina M", "role": "manager"},
            {"email": "hk1@prov.com", "name": "Hank K", "role": "housekeeper"},
        ],
    }
    body.update(overrides)
    return body


async def test_provision_happy_path(client, admin_user):
    r = await client.post(
        "/api/v1/hotels/provision",
        headers=auth_headers(admin_user),
        json=_payload(),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["hotel"]["name"] == "Provisioned Inn"
    assert body["rooms_created"] == 2
    assert len(body["users"]) == 2
    assert all(u["must_change_password"] is True for u in body["users"])
    assert body["temporary_password"]
    # room_type is normalized to uppercase by RoomCreate.
    # The shared temp password actually works for a provisioned user.
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "gm@prov.com", "password": body["temporary_password"]},
    )
    assert login.status_code == 200


async def test_provision_empty_lists(client, admin_user):
    r = await client.post(
        "/api/v1/hotels/provision",
        headers=auth_headers(admin_user),
        json={"hotel": {"name": "Bare Hotel"}, "rooms": [], "users": []},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["rooms_created"] == 0
    assert body["users"] == []


async def test_provision_lists_optional(client, admin_user):
    """rooms/users may be omitted entirely."""
    r = await client.post(
        "/api/v1/hotels/provision",
        headers=auth_headers(admin_user),
        json={"hotel": {"name": "Minimal Hotel"}},
    )
    assert r.status_code == 201
    assert r.json()["rooms_created"] == 0


async def test_provision_duplicate_room_number_in_batch(client, admin_user):
    r = await client.post(
        "/api/v1/hotels/provision",
        headers=auth_headers(admin_user),
        json=_payload(
            rooms=[{"room_number": "101"}, {"room_number": "101"}]
        ),
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert any(e["sheet"] == "rooms" for e in detail["errors"])


async def test_provision_duplicate_email_in_batch(client, admin_user):
    r = await client.post(
        "/api/v1/hotels/provision",
        headers=auth_headers(admin_user),
        json=_payload(
            users=[
                {"email": "dup@prov.com", "name": "A", "role": "manager"},
                {"email": "DUP@prov.com", "name": "B", "role": "housekeeper"},
            ]
        ),
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert any(e["field"] == "email" for e in detail["errors"])


async def test_provision_preexisting_email(client, admin_user):
    r = await client.post(
        "/api/v1/hotels/provision",
        headers=auth_headers(admin_user),
        json=_payload(
            users=[{"email": "admin@test.com", "name": "Clash", "role": "manager"}]
        ),
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert any("already exists" in e["message"] for e in detail["errors"])


async def test_provision_rejects_admin_role(client, admin_user):
    r = await client.post(
        "/api/v1/hotels/provision",
        headers=auth_headers(admin_user),
        json=_payload(
            users=[{"email": "a@prov.com", "name": "A", "role": "admin"}]
        ),
    )
    # Pydantic field validation rejects the role before the handler runs.
    assert r.status_code == 422


async def test_provision_requires_admin(client, manager_user):
    r = await client.post(
        "/api/v1/hotels/provision",
        headers=auth_headers(manager_user),
        json=_payload(),
    )
    assert r.status_code == 403


async def test_provision_is_all_or_nothing(client, admin_user):
    """A bad user row rolls back the whole batch — the hotel is never created."""
    r = await client.post(
        "/api/v1/hotels/provision",
        headers=auth_headers(admin_user),
        json=_payload(
            hotel={"name": "Ghost Hotel"},
            users=[{"email": "admin@test.com", "name": "X", "role": "manager"}],
        ),
    )
    assert r.status_code == 422
    listing = await client.get(
        "/api/v1/hotels", headers=auth_headers(admin_user)
    )
    names = {h["name"] for h in listing.json()}
    assert "Ghost Hotel" not in names
