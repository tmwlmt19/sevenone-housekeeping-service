"""Welcome email on user creation.

Every path that creates a staff account (admin provisioning + an approved
staff-add request) emails the new user their temp password and a sign-in link.
The sender is patched so tests never touch the network; we assert on the
recorded calls. Delivery is best-effort: a provider failure must not fail the
account creation.
"""
import pytest

from app import email as email_module
from app.routers import access_requests as ar_router
from app.routers import hotels as hotels_router
from conftest import auth_headers


@pytest.fixture(autouse=True)
def _capture_welcome(monkeypatch):
    """Patch the best-effort sender the routers imported; record calls."""
    calls = []

    async def _fake_send(*, to: str, name: str, temp_password: str) -> None:
        calls.append({"to": to, "name": name, "temp_password": temp_password})

    monkeypatch.setattr(hotels_router, "send_welcome_email_best_effort", _fake_send)
    monkeypatch.setattr(ar_router, "send_welcome_email_best_effort", _fake_send)
    return calls


def _provision_payload():
    return {
        "hotel": {"name": "Welcome Inn"},
        "rooms": [],
        "users": [
            {"email": "gm@welcome.com", "name": "Gina M", "role": "manager"},
            {"email": "fd@welcome.com", "name": "Fred D", "role": "front_desk"},
            {"email": "hk@welcome.com", "name": "Hank K", "role": "housekeeper"},
        ],
    }


# --------------------------------------------------------------------------- #
# Provisioning
# --------------------------------------------------------------------------- #


async def test_provision_welcomes_every_user(client, admin_user, _capture_welcome):
    r = await client.post(
        "/api/v1/hotels/provision",
        headers=auth_headers(admin_user),
        json=_provision_payload(),
    )
    assert r.status_code == 201
    temp = r.json()["temporary_password"]

    assert {c["to"] for c in _capture_welcome} == {
        "gm@welcome.com",
        "fd@welcome.com",
        "hk@welcome.com",
    }
    # Everyone gets the batch's shared temp password.
    assert all(c["temp_password"] == temp for c in _capture_welcome)


async def test_provision_with_no_users_sends_nothing(
    client, admin_user, _capture_welcome
):
    r = await client.post(
        "/api/v1/hotels/provision",
        headers=auth_headers(admin_user),
        json={"hotel": {"name": "Empty Inn"}, "rooms": [], "users": []},
    )
    assert r.status_code == 201
    assert _capture_welcome == []


# --------------------------------------------------------------------------- #
# Approved staff-add request
# --------------------------------------------------------------------------- #


async def _file_staff_add(client, manager_user, test_hotel):
    return await client.post(
        f"/api/v1/hotels/{test_hotel.id}/access-requests",
        headers=auth_headers(manager_user),
        json={
            "resource": "staff",
            "kind": "add",
            "payload": {
                "email": "newhire@welcome.com",
                "name": "Nadia Hire",
                "role": "housekeeper",
            },
        },
    )


async def test_approving_staff_add_welcomes_the_new_user(
    client, manager_user, service_admin, test_hotel, _capture_welcome
):
    filed = await _file_staff_add(client, manager_user, test_hotel)
    request_id = filed.json()["id"]

    r = await client.post(
        f"/api/v1/access-requests/{request_id}/approve",
        headers=auth_headers(service_admin),
    )
    assert r.status_code == 200
    temp = r.json()["temporary_password"]

    assert len(_capture_welcome) == 1
    call = _capture_welcome[0]
    assert call["to"] == "newhire@welcome.com"
    assert call["name"] == "Nadia Hire"
    assert call["temp_password"] == temp


async def test_approving_room_add_sends_no_welcome(
    client, manager_user, service_admin, test_hotel, _capture_welcome
):
    filed = await client.post(
        f"/api/v1/hotels/{test_hotel.id}/access-requests",
        headers=auth_headers(manager_user),
        json={
            "resource": "room",
            "kind": "add",
            "payload": {"room_number": "701", "room_type": "std"},
        },
    )
    request_id = filed.json()["id"]

    r = await client.post(
        f"/api/v1/access-requests/{request_id}/approve",
        headers=auth_headers(service_admin),
    )
    assert r.status_code == 200
    assert _capture_welcome == []


async def test_rejecting_staff_add_sends_no_welcome(
    client, manager_user, service_admin, test_hotel, _capture_welcome
):
    filed = await _file_staff_add(client, manager_user, test_hotel)
    request_id = filed.json()["id"]

    r = await client.post(
        f"/api/v1/access-requests/{request_id}/reject",
        headers=auth_headers(service_admin),
        json={"decision_note": "not now"},
    )
    assert r.status_code == 200
    assert _capture_welcome == []


# --------------------------------------------------------------------------- #
# Best-effort delivery
# --------------------------------------------------------------------------- #


async def test_best_effort_swallows_provider_error(monkeypatch, caplog):
    """A provider failure is logged, not raised — the caller (which has already
    created the account) must not see it."""

    async def _boom(*, to, name, temp_password):
        raise RuntimeError("provider down")

    monkeypatch.setattr(email_module, "send_welcome_email", _boom)

    # Should not raise.
    await email_module.send_welcome_email_best_effort(
        to="x@test.com", name="X", temp_password="pw"
    )
