"""PMS JSON entry point: POST /api/v1/integrations/pms/dirty-rooms.

Covers API-key authentication, tenant scoping (hotel derived from the key),
name-based housekeeper resolution, and the flexible payload adapter. The core
import behavior (dedupe, all-or-nothing, balancing) is proven in
test_task_import.py; here we focus on what's specific to this path.
"""

from datetime import datetime, timezone

from app.auth import hash_api_key
from app.models.enums import RoomStatus, UserRole
from app.models.hotel_api_key import HotelApiKey
from app.models.room import Room
from app.models.user import User

URL = "/api/v1/integrations/pms/dirty-rooms"


async def _room(db, hotel, number, status=RoomStatus.CLEAN):
    room = Room(hotel_id=hotel.id, room_number=number, status=status)
    db.add(room)
    await db.flush()
    return room


async def _housekeeper(db, hotel, email, name):
    user = User(
        hotel_id=hotel.id,
        email=email,
        password_hash="x",
        name=name,
        role=UserRole.HOUSEKEEPER,
    )
    db.add(user)
    await db.flush()
    return user


async def _api_key(db, hotel, raw="so_pms_testkey123", revoked=False):
    key = HotelApiKey(
        hotel_id=hotel.id,
        name="Test PMS",
        key_prefix=raw[:13],
        key_hash=hash_api_key(raw),
        revoked_at=datetime.now(timezone.utc) if revoked else None,
    )
    db.add(key)
    await db.flush()
    return key, raw


def _headers(raw_key):
    return {"X-API-Key": raw_key}


# --- Auth -------------------------------------------------------------------


async def test_pms_missing_key_401(client, db_session, test_hotel):
    await _room(db_session, test_hotel, "201")
    r = await client.post(URL, json={"rooms": ["201"]})
    assert r.status_code == 401


async def test_pms_invalid_key_401(client, db_session, test_hotel):
    await _room(db_session, test_hotel, "201")
    r = await client.post(URL, headers=_headers("so_pms_nope"), json={"rooms": ["201"]})
    assert r.status_code == 401


async def test_pms_revoked_key_401(client, db_session, test_hotel):
    await _room(db_session, test_hotel, "201")
    _, raw = await _api_key(db_session, test_hotel, revoked=True)
    r = await client.post(URL, headers=_headers(raw), json={"rooms": ["201"]})
    assert r.status_code == 401


# --- Tenant scoping ---------------------------------------------------------


async def test_pms_key_is_scoped_to_its_hotel(
    client, db_session, test_hotel, other_hotel
):
    # Room "301" exists only in the OTHER hotel; a test_hotel key must not reach
    # it — it should be reported as unknown (hotel comes from the key, not input).
    await _room(db_session, test_hotel, "201")
    await _room(db_session, other_hotel, "301")
    _, raw = await _api_key(db_session, test_hotel)

    ok = await client.post(URL, headers=_headers(raw), json={"rooms": ["201"]})
    assert ok.status_code == 201
    assert ok.json()["tasks_created"] == 1

    cross = await client.post(URL, headers=_headers(raw), json={"rooms": ["301"]})
    assert cross.status_code == 422


async def test_pms_updates_last_used_at(client, db_session, test_hotel):
    await _room(db_session, test_hotel, "201")
    key, raw = await _api_key(db_session, test_hotel)
    assert key.last_used_at is None

    r = await client.post(URL, headers=_headers(raw), json={"rooms": ["201"]})
    assert r.status_code == 201

    await db_session.refresh(key)
    assert key.last_used_at is not None


# --- Housekeeper resolution by name -----------------------------------------


async def test_pms_assigns_by_name(client, db_session, test_hotel):
    for n in ("201", "202", "203"):
        await _room(db_session, test_hotel, n)
    await _housekeeper(db_session, test_hotel, "maria@test.com", "Maria Ochoa")
    await _housekeeper(db_session, test_hotel, "carlos@test.com", "Carlos Diaz")
    _, raw = await _api_key(db_session, test_hotel)

    r = await client.post(
        URL,
        headers=_headers(raw),
        json={
            "rooms": ["201", "202", "203"],
            "housekeepers": ["Maria Ochoa", "carlos diaz"],  # case-insensitive
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["tasks_created"] == 3
    counts = sorted(a["tasks_assigned"] for a in body["assignments"])
    assert counts == [1, 2]


async def test_pms_unknown_name_rejected(client, db_session, test_hotel):
    await _room(db_session, test_hotel, "201")
    _, raw = await _api_key(db_session, test_hotel)
    r = await client.post(
        URL,
        headers=_headers(raw),
        json={"rooms": ["201"], "housekeepers": ["Nobody"]},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["errors"][0]["field"] == "housekeepers"


async def test_pms_ambiguous_name_rejected(client, db_session, test_hotel):
    await _room(db_session, test_hotel, "201")
    await _housekeeper(db_session, test_hotel, "m1@test.com", "Maria")
    await _housekeeper(db_session, test_hotel, "m2@test.com", "Maria")
    _, raw = await _api_key(db_session, test_hotel)
    r = await client.post(
        URL,
        headers=_headers(raw),
        json={"rooms": ["201"], "housekeepers": ["Maria"]},
    )
    assert r.status_code == 422


async def test_pms_no_housekeepers_leaves_unassigned(client, db_session, test_hotel):
    await _room(db_session, test_hotel, "201")
    _, raw = await _api_key(db_session, test_hotel)
    r = await client.post(URL, headers=_headers(raw), json={"rooms": ["201"]})
    assert r.status_code == 201
    assert r.json()["assignments"] == []


# --- Flexible payload adapter -----------------------------------------------


async def test_pms_accepts_object_and_string_room_shapes(
    client, db_session, test_hotel
):
    await _room(db_session, test_hotel, "201")
    await _room(db_session, test_hotel, "202")
    await _room(db_session, test_hotel, "203")
    _, raw = await _api_key(db_session, test_hotel)

    r = await client.post(
        URL,
        headers=_headers(raw),
        json={
            "rooms": [
                "201",
                {"room_number": "202"},
                {"room": "203"},  # alias
            ]
        },
    )
    assert r.status_code == 201
    assert r.json()["tasks_created"] == 3


async def test_pms_unrecognizable_room_entry_reported(
    client, db_session, test_hotel
):
    await _room(db_session, test_hotel, "201")
    _, raw = await _api_key(db_session, test_hotel)
    r = await client.post(
        URL,
        headers=_headers(raw),
        json={"rooms": ["201", {"floor": 3}]},  # no room number in the object
    )
    assert r.status_code == 422
    assert any(e["field"] == "rooms" for e in r.json()["detail"]["errors"])
