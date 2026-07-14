"""Self-service forgot-password flow.

The email sender is patched everywhere so tests never touch the network; we
assert on the tokens written to the DB and on the reset outcome.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.auth import hash_password
from app.models.enums import UserRole
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.routers import auth as auth_router


@pytest.fixture(autouse=True)
def _no_email(monkeypatch):
    """Patch the sender the router imported; record calls for assertions."""
    calls = []

    async def _fake_send(*, to: str, reset_url: str) -> None:
        calls.append({"to": to, "reset_url": reset_url})

    monkeypatch.setattr(auth_router, "send_password_reset_email", _fake_send)
    return calls


async def _token_count(db, user_id) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(PasswordResetToken)
        .where(PasswordResetToken.user_id == user_id)
    )
    return result.scalar_one()


async def test_forgot_unknown_email_returns_200_and_sends_nothing(
    client, _no_email
):
    r = await client.post(
        "/api/v1/auth/forgot-password", json={"email": "nobody@test.com"}
    )
    assert r.status_code == 200
    assert "reset link" in r.json()["message"]
    assert _no_email == []


async def test_forgot_known_email_mints_one_token_and_sends(
    client, db_session, admin_user, _no_email
):
    r = await client.post(
        "/api/v1/auth/forgot-password", json={"email": admin_user.email}
    )
    assert r.status_code == 200
    assert await _token_count(db_session, admin_user.id) == 1
    assert len(_no_email) == 1
    assert _no_email[0]["to"] == admin_user.email
    assert "token=" in _no_email[0]["reset_url"]


async def test_reset_sets_new_password_and_clears_flag(
    client, db_session, test_hotel, _no_email
):
    user = User(
        hotel_id=test_hotel.id,
        email="locked@test.com",
        password_hash=hash_password("oldpassword"),
        name="Locked Out",
        role=UserRole.HOUSEKEEPER,
        must_change_password=True,
    )
    db_session.add(user)
    await db_session.flush()

    await client.post(
        "/api/v1/auth/forgot-password", json={"email": user.email}
    )
    raw_token = _no_email[0]["reset_url"].split("token=", 1)[1]

    r = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": "brandnewpass1"},
    )
    assert r.status_code == 204

    # Old password no longer works; new one does.
    old = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "oldpassword"},
    )
    assert old.status_code == 401
    new = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "brandnewpass1"},
    )
    assert new.status_code == 200

    await db_session.refresh(user)
    assert user.must_change_password is False


async def test_reset_with_garbage_token_is_rejected(client):
    r = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": "not-a-real-token", "new_password": "whatever123"},
    )
    assert r.status_code == 400


async def test_reset_token_is_single_use(
    client, db_session, admin_user, _no_email
):
    await client.post(
        "/api/v1/auth/forgot-password", json={"email": admin_user.email}
    )
    raw_token = _no_email[0]["reset_url"].split("token=", 1)[1]

    first = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": "firstchange1"},
    )
    assert first.status_code == 204

    second = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": "secondchange1"},
    )
    assert second.status_code == 400


async def test_reset_with_expired_token_is_rejected(
    client, db_session, admin_user
):
    token = PasswordResetToken(
        user_id=admin_user.id,
        token_hash=auth_router._hash_token("expired-raw-token"),
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db_session.add(token)
    await db_session.flush()

    r = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": "expired-raw-token", "new_password": "whatever123"},
    )
    assert r.status_code == 400


async def test_per_user_throttle_skips_second_immediate_request(
    client, db_session, admin_user, _no_email
):
    await client.post(
        "/api/v1/auth/forgot-password", json={"email": admin_user.email}
    )
    await client.post(
        "/api/v1/auth/forgot-password", json={"email": admin_user.email}
    )
    # Second request is throttled: no new token minted, no second send.
    assert await _token_count(db_session, admin_user.id) == 1
    assert len(_no_email) == 1
