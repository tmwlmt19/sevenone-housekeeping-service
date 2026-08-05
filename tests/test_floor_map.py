"""Floor-map API: GET /map (view) and PUT /map/{floor} (edit).

RBAC is web-app-scoped: managers + front desk view, only managers edit; platform
admins are intentionally excluded from both (they live in the owner console).
See app/routers/floor_maps.py and hotel-map-plan.md.
"""

import uuid

from conftest import auth_headers

from app.models.enums import RoomStatus
from app.models.room import Room


async def _add_room(db, hotel, number: str, floor: int | None) -> Room:
    room = Room(
        hotel_id=hotel.id,
        room_number=number,
        floor=floor,
        room_type="STD",
        status=RoomStatus.DIRTY,
    )
    db.add(room)
    await db.flush()
    return room


def _floor(body: dict, floor: int) -> dict:
    return next(f for f in body["floors"] if f["floor"] == floor)


# --- GET /map : viewing ---------------------------------------------------


async def test_manager_sees_unplaced_rooms(
    client, manager_user, test_hotel, test_room
):
    r = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/map",
        headers=auth_headers(manager_user),
    )
    assert r.status_code == 200
    floor1 = _floor(r.json(), 1)
    # No saved map yet → null dimensions, grid defaults to 1.
    assert floor1["width_ft"] is None
    assert floor1["grid_ft"] == 1
    room = next(rm for rm in floor1["rooms"] if rm["id"] == str(test_room.id))
    assert room["placement"] is None
    assert room["status"] == "dirty"


async def test_front_desk_can_view(client, front_desk_user, test_hotel, test_room):
    r = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/map",
        headers=auth_headers(front_desk_user),
    )
    assert r.status_code == 200


async def test_admin_cannot_view(client, admin_user, test_hotel, test_room):
    # Platform admins are deliberately excluded from the floor map.
    r = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/map",
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 403


async def test_housekeeper_cannot_view(
    client, housekeeper_user, test_hotel, test_room
):
    r = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/map",
        headers=auth_headers(housekeeper_user),
    )
    assert r.status_code == 403


async def test_view_other_hotel_is_404(
    client, manager_user, other_hotel, test_room
):
    # Tenant isolation: a manager cannot read another hotel's map.
    r = await client.get(
        f"/api/v1/hotels/{other_hotel.id}/map",
        headers=auth_headers(manager_user),
    )
    assert r.status_code == 404


async def test_rooms_without_a_floor_are_excluded(
    client, manager_user, test_hotel, db_session
):
    await _add_room(db_session, test_hotel, "999", None)
    r = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/map",
        headers=auth_headers(manager_user),
    )
    assert r.status_code == 200
    all_room_ids = [
        rm["id"] for f in r.json()["floors"] for rm in f["rooms"]
    ]
    # The floor-less room appears nowhere on the map.
    assert all_room_ids == [] or "999" not in [
        rm["room_number"]
        for f in r.json()["floors"]
        for rm in f["rooms"]
    ]


# --- PUT /map/{floor} : editing -------------------------------------------


async def test_manager_saves_layout(client, manager_user, test_hotel, test_room):
    body = {
        "name": "Ground Floor",
        "width_ft": 200,
        "height_ft": 60,
        "grid_ft": 1,
        "decorations": [
            {"kind": "hall", "x": 0, "y": 12, "w": 200, "h": 6},
            {"kind": "stairs", "x": 4, "y": 0, "w": 8, "h": 10, "label": "S1"},
        ],
        "placements": [
            {
                "room_id": str(test_room.id),
                "x": 10,
                "y": 20,
                "w": 13,
                "h": 26,
                "rotation": 90,
            }
        ],
    }
    r = await client.put(
        f"/api/v1/hotels/{test_hotel.id}/map/1",
        headers=auth_headers(manager_user),
        json=body,
    )
    assert r.status_code == 200
    out = r.json()
    assert out["name"] == "Ground Floor"
    assert len(out["decorations"]) == 2
    placed = next(rm for rm in out["rooms"] if rm["id"] == str(test_room.id))
    assert placed["placement"] == {
        "x": 10, "y": 20, "w": 13, "h": 26, "rotation": 90,
    }

    # And it persists: a follow-up GET shows the placement.
    got = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/map",
        headers=auth_headers(manager_user),
    )
    floor1 = _floor(got.json(), 1)
    assert floor1["width_ft"] == 200
    room = next(rm for rm in floor1["rooms"] if rm["id"] == str(test_room.id))
    assert room["placement"]["x"] == 10


async def test_front_desk_cannot_edit(
    client, front_desk_user, test_hotel, test_room
):
    r = await client.put(
        f"/api/v1/hotels/{test_hotel.id}/map/1",
        headers=auth_headers(front_desk_user),
        json={"width_ft": 100, "height_ft": 50, "placements": []},
    )
    assert r.status_code == 403


async def test_admin_cannot_edit(client, admin_user, test_hotel, test_room):
    r = await client.put(
        f"/api/v1/hotels/{test_hotel.id}/map/1",
        headers=auth_headers(admin_user),
        json={"width_ft": 100, "height_ft": 50, "placements": []},
    )
    assert r.status_code == 403


async def test_edit_other_hotel_is_404(
    client, manager_user, other_hotel, test_room
):
    r = await client.put(
        f"/api/v1/hotels/{other_hotel.id}/map/1",
        headers=auth_headers(manager_user),
        json={"width_ft": 100, "height_ft": 50, "placements": []},
    )
    assert r.status_code == 404


async def test_reject_room_on_a_different_floor(
    client, manager_user, test_hotel, test_room, db_session
):
    upstairs = await _add_room(db_session, test_hotel, "201", 2)
    r = await client.put(
        f"/api/v1/hotels/{test_hotel.id}/map/1",
        headers=auth_headers(manager_user),
        json={
            "width_ft": 100,
            "height_ft": 50,
            "placements": [
                {"room_id": str(upstairs.id), "x": 0, "y": 0, "w": 10, "h": 10}
            ],
        },
    )
    assert r.status_code == 400


async def test_reject_cross_hotel_room(
    client, manager_user, test_hotel, other_hotel, db_session
):
    foreign = await _add_room(db_session, other_hotel, "101", 1)
    r = await client.put(
        f"/api/v1/hotels/{test_hotel.id}/map/1",
        headers=auth_headers(manager_user),
        json={
            "width_ft": 100,
            "height_ft": 50,
            "placements": [
                {"room_id": str(foreign.id), "x": 0, "y": 0, "w": 10, "h": 10}
            ],
        },
    )
    assert r.status_code == 400


async def test_reject_unknown_room(client, manager_user, test_hotel):
    r = await client.put(
        f"/api/v1/hotels/{test_hotel.id}/map/1",
        headers=auth_headers(manager_user),
        json={
            "width_ft": 100,
            "height_ft": 50,
            "placements": [
                {
                    "room_id": str(uuid.uuid4()),
                    "x": 0, "y": 0, "w": 10, "h": 10,
                }
            ],
        },
    )
    assert r.status_code == 400


async def test_full_floor_replace_unplaces_omitted_rooms(
    client, manager_user, test_hotel, test_room, db_session
):
    other = await _add_room(db_session, test_hotel, "102", 1)
    base = {"width_ft": 100, "height_ft": 50}
    # Place both rooms.
    r1 = await client.put(
        f"/api/v1/hotels/{test_hotel.id}/map/1",
        headers=auth_headers(manager_user),
        json={
            **base,
            "placements": [
                {"room_id": str(test_room.id), "x": 0, "y": 0, "w": 10, "h": 10},
                {"room_id": str(other.id), "x": 20, "y": 0, "w": 10, "h": 10},
            ],
        },
    )
    assert r1.status_code == 200
    # Re-save with only one → the other becomes unplaced.
    r2 = await client.put(
        f"/api/v1/hotels/{test_hotel.id}/map/1",
        headers=auth_headers(manager_user),
        json={
            **base,
            "placements": [
                {"room_id": str(test_room.id), "x": 5, "y": 5, "w": 10, "h": 10}
            ],
        },
    )
    assert r2.status_code == 200
    placements = {rm["id"]: rm["placement"] for rm in r2.json()["rooms"]}
    assert placements[str(test_room.id)] is not None
    assert placements[str(other.id)] is None


async def test_rotation_must_be_a_right_angle(
    client, manager_user, test_hotel, test_room
):
    r = await client.put(
        f"/api/v1/hotels/{test_hotel.id}/map/1",
        headers=auth_headers(manager_user),
        json={
            "width_ft": 100,
            "height_ft": 50,
            "placements": [
                {
                    "room_id": str(test_room.id),
                    "x": 0, "y": 0, "w": 10, "h": 10, "rotation": 45,
                }
            ],
        },
    )
    assert r.status_code == 422


async def test_zero_footprint_rejected(
    client, manager_user, test_hotel, test_room
):
    r = await client.put(
        f"/api/v1/hotels/{test_hotel.id}/map/1",
        headers=auth_headers(manager_user),
        json={
            "width_ft": 100,
            "height_ft": 50,
            "placements": [
                {"room_id": str(test_room.id), "x": 0, "y": 0, "w": 0, "h": 10}
            ],
        },
    )
    assert r.status_code == 422


# --- Decorations (their own addressable rows) -----------------------------

_MAP = {"width_ft": 100, "height_ft": 50, "placements": []}


async def test_new_decoration_gets_a_server_id(client, manager_user, test_hotel):
    r = await client.put(
        f"/api/v1/hotels/{test_hotel.id}/map/1",
        headers=auth_headers(manager_user),
        json={**_MAP, "decorations": [{"kind": "hall", "x": 0, "y": 12, "w": 100, "h": 6}]},
    )
    assert r.status_code == 200
    decos = r.json()["decorations"]
    assert len(decos) == 1
    assert decos[0]["id"]  # server-assigned
    assert decos[0]["kind"] == "hall"


async def test_label_may_have_zero_footprint(client, manager_user, test_hotel):
    r = await client.put(
        f"/api/v1/hotels/{test_hotel.id}/map/1",
        headers=auth_headers(manager_user),
        json={
            **_MAP,
            "decorations": [
                {"kind": "label", "x": 40, "y": 2, "w": 0, "h": 0, "label": "Wing A"}
            ],
        },
    )
    assert r.status_code == 200
    assert r.json()["decorations"][0]["label"] == "Wing A"


async def test_decoration_id_is_stable_across_saves(
    client, manager_user, test_hotel
):
    url = f"/api/v1/hotels/{test_hotel.id}/map/1"
    r1 = await client.put(
        url,
        headers=auth_headers(manager_user),
        json={**_MAP, "decorations": [{"kind": "elevator", "x": 0, "y": 0, "w": 8, "h": 8}]},
    )
    deco_id = r1.json()["decorations"][0]["id"]
    # Echo the id back with a new position → update in place, id preserved.
    r2 = await client.put(
        url,
        headers=auth_headers(manager_user),
        json={
            **_MAP,
            "decorations": [
                {"id": deco_id, "kind": "elevator", "x": 5, "y": 5, "w": 8, "h": 8}
            ],
        },
    )
    updated = r2.json()["decorations"]
    assert len(updated) == 1
    assert updated[0]["id"] == deco_id  # identity kept
    assert updated[0]["x"] == 5  # moved


async def test_omitted_decoration_is_pruned(client, manager_user, test_hotel):
    url = f"/api/v1/hotels/{test_hotel.id}/map/1"
    r1 = await client.put(
        url,
        headers=auth_headers(manager_user),
        json={
            **_MAP,
            "decorations": [
                {"kind": "hall", "x": 0, "y": 0, "w": 100, "h": 4},
                {"kind": "stairs", "x": 0, "y": 10, "w": 8, "h": 8, "label": "S1"},
            ],
        },
    )
    assert len(r1.json()["decorations"]) == 2
    keep = next(d for d in r1.json()["decorations"] if d["kind"] == "hall")
    # Re-save with only the hall → the stairs are pruned.
    r2 = await client.put(
        url,
        headers=auth_headers(manager_user),
        json={
            **_MAP,
            "decorations": [
                {"id": keep["id"], "kind": "hall", "x": 0, "y": 0, "w": 100, "h": 4}
            ],
        },
    )
    decos = r2.json()["decorations"]
    assert len(decos) == 1
    assert decos[0]["id"] == keep["id"]


async def test_invalid_decoration_kind_rejected(client, manager_user, test_hotel):
    r = await client.put(
        f"/api/v1/hotels/{test_hotel.id}/map/1",
        headers=auth_headers(manager_user),
        json={**_MAP, "decorations": [{"kind": "pool", "x": 0, "y": 0, "w": 5, "h": 5}]},
    )
    assert r.status_code == 422
