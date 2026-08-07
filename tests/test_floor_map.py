"""Floor-map API: GET /map (view) and PUT /map/{floor} (edit).

RBAC is web-app-scoped: managers + front desk view, only managers edit; platform
admins are intentionally excluded from both (they live in the owner console).
Geometry is absolute polygons (float feet); a rectangle is four right-angle
vertices. See app/routers/floor_maps.py and hotel-map-plan.md.
"""

import uuid

from conftest import auth_headers

from app.models.enums import RoomStatus, TaskStatus
from app.models.room import Room
from app.models.task import Task


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


def _rect(x: float, y: float, w: float, h: float) -> list[list[float]]:
    """A rectangle as four absolute vertices — the polygon a placement/decoration
    defaults to."""
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


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
    # No saved map yet → null dimensions/outline, grid defaults to 1.
    assert floor1["width_ft"] is None
    assert floor1["outline"] is None
    assert floor1["grid_ft"] == 1
    room = next(rm for rm in floor1["rooms"] if rm["id"] == str(test_room.id))
    assert room["placement"] is None
    assert room["status"] == "dirty"


async def test_map_flags_rooms_with_open_task(
    client, db_session, manager_user, test_hotel
):
    # A dirty room with a live task is flagged; a dirty room without one is not.
    tasked = await _add_room(db_session, test_hotel, "201", floor=1)
    untasked = await _add_room(db_session, test_hotel, "202", floor=1)
    db_session.add(
        Task(hotel_id=test_hotel.id, room_id=tasked.id, status=TaskStatus.ASSIGNED)
    )
    await db_session.flush()

    r = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/map",
        headers=auth_headers(manager_user),
    )
    assert r.status_code == 200
    by_id = {rm["id"]: rm for rm in _floor(r.json(), 1)["rooms"]}
    assert by_id[str(tasked.id)]["has_open_task"] is True
    assert by_id[str(untasked.id)]["has_open_task"] is False


async def test_map_open_task_ignores_completed(
    client, db_session, manager_user, test_hotel
):
    # A completed/archived task is not "open" — the room stays a candidate.
    room = await _add_room(db_session, test_hotel, "201", floor=1)
    db_session.add(
        Task(hotel_id=test_hotel.id, room_id=room.id, status=TaskStatus.COMPLETED)
    )
    await db_session.flush()

    r = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/map",
        headers=auth_headers(manager_user),
    )
    by_id = {rm["id"]: rm for rm in _floor(r.json(), 1)["rooms"]}
    assert by_id[str(room.id)]["has_open_task"] is False


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
    # The floor-less room appears nowhere on the map.
    assert "999" not in [
        rm["room_number"] for f in r.json()["floors"] for rm in f["rooms"]
    ]


# --- PUT /map/{floor} : editing -------------------------------------------


async def test_manager_saves_layout(client, manager_user, test_hotel, test_room):
    body = {
        "name": "Ground Floor",
        "width_ft": 200,
        "height_ft": 60,
        "grid_ft": 1,
        "outline": _rect(0, 0, 200, 60),
        "decorations": [
            {"kind": "hall", "vertices": _rect(0, 12, 200, 6)},
            {"kind": "stairs", "vertices": _rect(4, 0, 8, 10), "label": "S1"},
        ],
        "placements": [
            {
                "room_id": str(test_room.id),
                "vertices": _rect(10, 20, 13, 26),
                "door": {"edge": 2, "t": 0.5},
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
    assert out["outline"] == _rect(0, 0, 200, 60)
    assert len(out["decorations"]) == 2
    placed = next(rm for rm in out["rooms"] if rm["id"] == str(test_room.id))
    assert placed["placement"]["vertices"] == _rect(10, 20, 13, 26)
    assert placed["placement"]["door"] == {"edge": 2, "t": 0.5}

    # And it persists: a follow-up GET shows the placement.
    got = await client.get(
        f"/api/v1/hotels/{test_hotel.id}/map",
        headers=auth_headers(manager_user),
    )
    floor1 = _floor(got.json(), 1)
    assert floor1["width_ft"] == 200
    assert floor1["outline"] == _rect(0, 0, 200, 60)
    room = next(rm for rm in floor1["rooms"] if rm["id"] == str(test_room.id))
    assert room["placement"]["vertices"][0] == [10, 20]


async def test_placement_door_defaults_to_null(
    client, manager_user, test_hotel, test_room
):
    r = await client.put(
        f"/api/v1/hotels/{test_hotel.id}/map/1",
        headers=auth_headers(manager_user),
        json={
            "width_ft": 100,
            "height_ft": 50,
            "placements": [
                {"room_id": str(test_room.id), "vertices": _rect(0, 0, 10, 10)}
            ],
        },
    )
    assert r.status_code == 200
    placed = next(
        rm for rm in r.json()["rooms"] if rm["id"] == str(test_room.id)
    )
    assert placed["placement"]["door"] is None


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
                {"room_id": str(upstairs.id), "vertices": _rect(0, 0, 10, 10)}
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
                {"room_id": str(foreign.id), "vertices": _rect(0, 0, 10, 10)}
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
                {"room_id": str(uuid.uuid4()), "vertices": _rect(0, 0, 10, 10)}
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
                {"room_id": str(test_room.id), "vertices": _rect(0, 0, 10, 10)},
                {"room_id": str(other.id), "vertices": _rect(20, 0, 10, 10)},
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
                {"room_id": str(test_room.id), "vertices": _rect(5, 5, 10, 10)}
            ],
        },
    )
    assert r2.status_code == 200
    placements = {rm["id"]: rm["placement"] for rm in r2.json()["rooms"]}
    assert placements[str(test_room.id)] is not None
    assert placements[str(other.id)] is None


# --- Polygon geometry validation ------------------------------------------


async def test_rotated_polygon_is_accepted(
    client, manager_user, test_hotel, test_room
):
    # A diamond (a square rotated 45°) — no longer a right-angle-only world.
    diamond = [[10, 0], [20, 10], [10, 20], [0, 10]]
    r = await client.put(
        f"/api/v1/hotels/{test_hotel.id}/map/1",
        headers=auth_headers(manager_user),
        json={
            "width_ft": 100,
            "height_ft": 50,
            "placements": [
                {"room_id": str(test_room.id), "vertices": diamond}
            ],
        },
    )
    assert r.status_code == 200
    placed = next(
        rm for rm in r.json()["rooms"] if rm["id"] == str(test_room.id)
    )
    assert placed["placement"]["vertices"] == diamond


async def test_self_intersecting_polygon_rejected(
    client, manager_user, test_hotel, test_room
):
    bowtie = [[0, 0], [10, 10], [10, 0], [0, 10]]
    r = await client.put(
        f"/api/v1/hotels/{test_hotel.id}/map/1",
        headers=auth_headers(manager_user),
        json={
            "width_ft": 100,
            "height_ft": 50,
            "placements": [
                {"room_id": str(test_room.id), "vertices": bowtie}
            ],
        },
    )
    assert r.status_code == 422


async def test_too_few_vertices_rejected(
    client, manager_user, test_hotel, test_room
):
    r = await client.put(
        f"/api/v1/hotels/{test_hotel.id}/map/1",
        headers=auth_headers(manager_user),
        json={
            "width_ft": 100,
            "height_ft": 50,
            "placements": [
                {"room_id": str(test_room.id), "vertices": [[0, 0], [10, 10]]}
            ],
        },
    )
    assert r.status_code == 422


async def test_zero_area_polygon_rejected(
    client, manager_user, test_hotel, test_room
):
    # Three collinear points enclose no area.
    r = await client.put(
        f"/api/v1/hotels/{test_hotel.id}/map/1",
        headers=auth_headers(manager_user),
        json={
            "width_ft": 100,
            "height_ft": 50,
            "placements": [
                {
                    "room_id": str(test_room.id),
                    "vertices": [[0, 0], [10, 0], [20, 0]],
                }
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
        json={**_MAP, "decorations": [{"kind": "hall", "vertices": _rect(0, 12, 100, 6)}]},
    )
    assert r.status_code == 200
    decos = r.json()["decorations"]
    assert len(decos) == 1
    assert decos[0]["id"]  # server-assigned
    assert decos[0]["kind"] == "hall"


async def test_label_is_an_anchor_point(client, manager_user, test_hotel):
    # A label carries a single anchor point, not a filled polygon.
    r = await client.put(
        f"/api/v1/hotels/{test_hotel.id}/map/1",
        headers=auth_headers(manager_user),
        json={
            **_MAP,
            "decorations": [
                {"kind": "label", "vertices": [[40, 2]], "label": "Wing A"}
            ],
        },
    )
    assert r.status_code == 200
    deco = r.json()["decorations"][0]
    assert deco["label"] == "Wing A"
    assert deco["vertices"] == [[40, 2]]


async def test_decoration_id_is_stable_across_saves(
    client, manager_user, test_hotel
):
    url = f"/api/v1/hotels/{test_hotel.id}/map/1"
    r1 = await client.put(
        url,
        headers=auth_headers(manager_user),
        json={**_MAP, "decorations": [{"kind": "elevator", "vertices": _rect(0, 0, 8, 8)}]},
    )
    deco_id = r1.json()["decorations"][0]["id"]
    # Echo the id back with a new position → update in place, id preserved.
    r2 = await client.put(
        url,
        headers=auth_headers(manager_user),
        json={
            **_MAP,
            "decorations": [
                {"id": deco_id, "kind": "elevator", "vertices": _rect(5, 5, 8, 8)}
            ],
        },
    )
    updated = r2.json()["decorations"]
    assert len(updated) == 1
    assert updated[0]["id"] == deco_id  # identity kept
    assert updated[0]["vertices"][0] == [5, 5]  # moved


async def test_omitted_decoration_is_pruned(client, manager_user, test_hotel):
    url = f"/api/v1/hotels/{test_hotel.id}/map/1"
    r1 = await client.put(
        url,
        headers=auth_headers(manager_user),
        json={
            **_MAP,
            "decorations": [
                {"kind": "hall", "vertices": _rect(0, 0, 100, 4)},
                {"kind": "stairs", "vertices": _rect(0, 10, 8, 8), "label": "S1"},
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
                {"id": keep["id"], "kind": "hall", "vertices": _rect(0, 0, 100, 4)}
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
        json={**_MAP, "decorations": [{"kind": "pool", "vertices": _rect(0, 0, 5, 5)}]},
    )
    assert r.status_code == 422
