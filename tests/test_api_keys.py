"""Admin management of per-hotel PMS API keys:
GET/POST /hotels/{id}/api-keys and DELETE /hotels/{id}/api-keys/{key_id}.
"""

import uuid

from conftest import auth_headers

from app.auth import API_KEY_PREFIX


def _base(hotel):
    return f"/api/v1/hotels/{hotel.id}/api-keys"


async def test_create_returns_secret_once(client, test_hotel, service_admin):
    r = await client.post(
        _base(test_hotel),
        headers=auth_headers(service_admin),
        json={"name": "Opera PMS"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["key"].startswith(API_KEY_PREFIX)
    assert body["api_key"]["name"] == "Opera PMS"
    assert body["api_key"]["revoked_at"] is None
    # The listed prefix is a prefix of the full secret, never the whole thing.
    assert body["key"].startswith(body["api_key"]["key_prefix"])
    assert len(body["api_key"]["key_prefix"]) < len(body["key"])


async def test_list_never_exposes_secret(client, test_hotel, service_admin):
    await client.post(
        _base(test_hotel),
        headers=auth_headers(service_admin),
        json={"name": "K1"},
    )
    r = await client.get(_base(test_hotel), headers=auth_headers(service_admin))
    assert r.status_code == 200
    keys = r.json()
    assert len(keys) == 1
    assert "key" not in keys[0]
    assert "key_hash" not in keys[0]


async def test_revoke_disables_key(client, test_hotel, service_admin):
    created = (
        await client.post(
            _base(test_hotel),
            headers=auth_headers(service_admin),
            json={"name": "K1"},
        )
    ).json()
    key_id = created["api_key"]["id"]

    r = await client.delete(
        f"{_base(test_hotel)}/{key_id}", headers=auth_headers(service_admin)
    )
    assert r.status_code == 204

    keys = (
        await client.get(_base(test_hotel), headers=auth_headers(service_admin))
    ).json()
    assert keys[0]["revoked_at"] is not None


async def test_revoke_is_idempotent(client, test_hotel, service_admin):
    created = (
        await client.post(
            _base(test_hotel),
            headers=auth_headers(service_admin),
            json={"name": "K1"},
        )
    ).json()
    key_id = created["api_key"]["id"]
    url = f"{_base(test_hotel)}/{key_id}"
    assert (await client.delete(url, headers=auth_headers(service_admin))).status_code == 204
    assert (await client.delete(url, headers=auth_headers(service_admin))).status_code == 204


async def test_revoke_unknown_key_404(client, test_hotel, service_admin):
    r = await client.delete(
        f"{_base(test_hotel)}/{uuid.uuid4()}",
        headers=auth_headers(service_admin),
    )
    assert r.status_code == 404


async def test_revoke_key_from_other_hotel_404(
    client, test_hotel, other_hotel, service_admin
):
    created = (
        await client.post(
            _base(other_hotel),
            headers=auth_headers(service_admin),
            json={"name": "Foreign"},
        )
    ).json()
    key_id = created["api_key"]["id"]
    # Same key id, but addressed under the wrong hotel -> not found.
    r = await client.delete(
        f"{_base(test_hotel)}/{key_id}", headers=auth_headers(service_admin)
    )
    assert r.status_code == 404


# --- RBAC -------------------------------------------------------------------


async def test_manager_cannot_manage_keys(client, test_hotel, manager_user):
    assert (
        await client.get(_base(test_hotel), headers=auth_headers(manager_user))
    ).status_code == 403
    assert (
        await client.post(
            _base(test_hotel),
            headers=auth_headers(manager_user),
            json={"name": "x"},
        )
    ).status_code == 403


async def test_unknown_hotel_404(client, service_admin):
    r = await client.post(
        f"/api/v1/hotels/{uuid.uuid4()}/api-keys",
        headers=auth_headers(service_admin),
        json={"name": "x"},
    )
    assert r.status_code == 404
