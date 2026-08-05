"""Manager (CSV) bulk dirty-room import: POST /hotels/{id}/tasks/import.

Exercises the shared import core (app/services/task_import.py) through the
cookie-authenticated manager endpoint. The PMS path is covered in
test_integrations_pms.py; both share this core.
"""

import uuid

from conftest import auth_headers

from app.models.enums import RoomStatus, TaskStatus, UserRole
from app.models.room import Room
from app.models.task import Task
from app.models.user import User


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


async def _assigned_task(db, hotel, room, hk):
    task = Task(
        hotel_id=hotel.id,
        room_id=room.id,
        assigned_to=hk.id,
        status=TaskStatus.ASSIGNED,
    )
    db.add(task)
    await db.flush()
    return task


def _import(client, hotel, manager, **body):
    return client.post(
        f"/api/v1/hotels/{hotel.id}/tasks/import",
        headers=auth_headers(manager),
        json=body,
    )


# --- Happy paths ------------------------------------------------------------


async def test_import_creates_tasks_and_sets_rooms_dirty_unassigned(
    client, db_session, test_hotel, manager_user
):
    await _room(db_session, test_hotel, "201")
    await _room(db_session, test_hotel, "202")

    r = await _import(client, test_hotel, manager_user, rooms=["201", "202"])

    assert r.status_code == 201
    body = r.json()
    assert body["tasks_created"] == 2
    assert body["rooms_set_dirty"] == 2
    assert body["skipped"] == []
    assert body["assignments"] == []

    tasks = (
        await client.get(
            f"/api/v1/hotels/{test_hotel.id}/tasks",
            headers=auth_headers(manager_user),
        )
    ).json()
    assert len(tasks) == 2
    assert all(t["status"] == "pending" and t["assigned_to"] is None for t in tasks)
    assert all(t["due_date"] is not None for t in tasks)


async def test_import_default_priority_and_override(
    client, db_session, test_hotel, manager_user
):
    await _room(db_session, test_hotel, "201")
    await _room(db_session, test_hotel, "202")

    r = await _import(
        client, test_hotel, manager_user, rooms=["201"], priority="urgent"
    )
    assert r.status_code == 201
    r2 = await _import(client, test_hotel, manager_user, rooms=["202"])
    assert r2.status_code == 201

    tasks = (
        await client.get(
            f"/api/v1/hotels/{test_hotel.id}/tasks",
            headers=auth_headers(manager_user),
        )
    ).json()
    priorities = {t["room_id"]: t["priority"] for t in tasks}
    assert "urgent" in priorities.values()
    assert "normal" in priorities.values()


# --- Skips (soft, reported, not errors) -------------------------------------


async def test_import_skips_room_with_open_task(
    client, db_session, test_hotel, manager_user, housekeeper_user
):
    room = await _room(db_session, test_hotel, "201", status=RoomStatus.CLEAN)
    await _assigned_task(db_session, test_hotel, room, housekeeper_user)

    r = await _import(client, test_hotel, manager_user, rooms=["201"])

    assert r.status_code == 201
    body = r.json()
    assert body["tasks_created"] == 0
    assert body["rooms_set_dirty"] == 1  # still flipped dirty
    assert body["skipped"] == [
        {"room_number": "201", "reason": "existing_open_task"}
    ]


async def test_import_retasks_room_with_only_completed_task(
    client, db_session, test_hotel, manager_user, housekeeper_user
):
    room = await _room(db_session, test_hotel, "201")
    done = Task(
        hotel_id=test_hotel.id,
        room_id=room.id,
        assigned_to=housekeeper_user.id,
        status=TaskStatus.COMPLETED,
    )
    db_session.add(done)
    await db_session.flush()

    r = await _import(client, test_hotel, manager_user, rooms=["201"])

    assert r.status_code == 201
    assert r.json()["tasks_created"] == 1  # completed task doesn't block


async def test_import_skips_room_with_pending_approval_task(
    client, db_session, test_hotel, manager_user, housekeeper_user
):
    # Cleaned but awaiting manager sign-off: the room isn't "clean" yet, so the
    # next day's dirty-room report still lists it. A re-import must skip it, not
    # raise a second task on top of the one waiting for approval.
    room = await _room(db_session, test_hotel, "201", status=RoomStatus.DIRTY)
    pending = Task(
        hotel_id=test_hotel.id,
        room_id=room.id,
        assigned_to=housekeeper_user.id,
        status=TaskStatus.PENDING_APPROVAL,
    )
    db_session.add(pending)
    await db_session.flush()

    r = await _import(client, test_hotel, manager_user, rooms=["201"])

    assert r.status_code == 201
    body = r.json()
    assert body["tasks_created"] == 0
    assert body["skipped"] == [
        {"room_number": "201", "reason": "existing_open_task"}
    ]


async def test_import_skips_out_of_service_room(
    client, db_session, test_hotel, manager_user
):
    await _room(db_session, test_hotel, "201", status=RoomStatus.OUT_OF_SERVICE)
    await _room(db_session, test_hotel, "202")

    r = await _import(client, test_hotel, manager_user, rooms=["201", "202"])

    assert r.status_code == 201
    body = r.json()
    assert body["tasks_created"] == 1
    assert body["rooms_set_dirty"] == 1  # OOS room not flipped
    assert body["skipped"] == [{"room_number": "201", "reason": "out_of_service"}]

    rooms = (
        await client.get(
            f"/api/v1/hotels/{test_hotel.id}/rooms",
            headers=auth_headers(manager_user),
        )
    ).json()
    oos = next(rm for rm in rooms if rm["room_number"] == "201")
    assert oos["status"] == "out_of_service"


# --- All-or-nothing validation ----------------------------------------------


async def test_import_unknown_room_rejects_whole_batch(
    client, db_session, test_hotel, manager_user
):
    await _room(db_session, test_hotel, "201")

    r = await _import(
        client, test_hotel, manager_user, rooms=["201", "999", "998"]
    )

    assert r.status_code == 422
    errors = r.json()["detail"]["errors"]
    bad = {e["value"] for e in errors}
    assert bad == {"999", "998"}

    # Nothing created, and the known room was NOT flipped dirty.
    tasks = (
        await client.get(
            f"/api/v1/hotels/{test_hotel.id}/tasks",
            headers=auth_headers(manager_user),
        )
    ).json()
    assert tasks == []
    rooms = (
        await client.get(
            f"/api/v1/hotels/{test_hotel.id}/rooms",
            headers=auth_headers(manager_user),
        )
    ).json()
    assert all(rm["status"] == "clean" for rm in rooms if rm["room_number"] == "201")


async def test_import_empty_rooms_rejected(client, test_hotel, manager_user):
    r = await _import(client, test_hotel, manager_user, rooms=[])
    assert r.status_code == 422


async def test_import_non_housekeeper_id_rejected(
    client, db_session, test_hotel, manager_user
):
    await _room(db_session, test_hotel, "201")
    # A manager id is not a housekeeper -> rejected.
    r = await _import(
        client,
        test_hotel,
        manager_user,
        rooms=["201"],
        housekeeper_ids=[str(manager_user.id)],
    )
    assert r.status_code == 422
    assert r.json()["detail"]["errors"][0]["field"] == "housekeeper_ids"


async def test_import_cross_hotel_housekeeper_rejected(
    client, db_session, test_hotel, manager_user, other_hotel
):
    await _room(db_session, test_hotel, "201")
    foreign_hk = await _housekeeper(
        db_session, other_hotel, "foreign-hk@test.com", "Foreign HK"
    )

    r = await _import(
        client,
        test_hotel,
        manager_user,
        rooms=["201"],
        housekeeper_ids=[str(foreign_hk.id)],
    )
    assert r.status_code == 422


# --- RBAC / tenant isolation ------------------------------------------------


async def test_import_requires_manager(
    client, db_session, test_hotel, housekeeper_user
):
    await _room(db_session, test_hotel, "201")
    r = await _import(client, test_hotel, housekeeper_user, rooms=["201"])
    assert r.status_code == 403


async def test_import_cross_hotel_forbidden(
    client, db_session, other_hotel, manager_user
):
    await _room(db_session, other_hotel, "201")
    # manager_user belongs to test_hotel, targets other_hotel.
    r = await client.post(
        f"/api/v1/hotels/{other_hotel.id}/tasks/import",
        headers=auth_headers(manager_user),
        json={"rooms": ["201"]},
    )
    assert r.status_code == 404


# --- Assignment / balancing -------------------------------------------------


async def test_import_balances_evenly_no_prior_load(
    client, db_session, test_hotel, manager_user
):
    for n in ("201", "202", "203", "204", "205"):
        await _room(db_session, test_hotel, n)
    hk_a = await _housekeeper(db_session, test_hotel, "a@test.com", "Ann")
    hk_b = await _housekeeper(db_session, test_hotel, "b@test.com", "Bob")

    r = await _import(
        client,
        test_hotel,
        manager_user,
        rooms=["201", "202", "203", "204", "205"],
        housekeeper_ids=[str(hk_a.id), str(hk_b.id)],
    )

    assert r.status_code == 201
    body = r.json()
    assert body["tasks_created"] == 5
    counts = sorted(a["tasks_assigned"] for a in body["assignments"])
    assert counts == [2, 3]  # even, differ by <= 1

    tasks = (
        await client.get(
            f"/api/v1/hotels/{test_hotel.id}/tasks",
            headers=auth_headers(manager_user),
        )
    ).json()
    assert all(t["status"] == "assigned" for t in tasks)
    assert all(t["assigned_to"] is not None for t in tasks)


async def test_import_balances_total_open_workload(
    client, db_session, test_hotel, manager_user
):
    # hk_a starts with 2 open tasks; hk_b with 0. Two new tasks should both go
    # to hk_b so final totals equalize at 2 each.
    hk_a = await _housekeeper(db_session, test_hotel, "a@test.com", "Ann")
    hk_b = await _housekeeper(db_session, test_hotel, "b@test.com", "Bob")
    pre1 = await _room(db_session, test_hotel, "101a")
    pre2 = await _room(db_session, test_hotel, "102a")
    await _assigned_task(db_session, test_hotel, pre1, hk_a)
    await _assigned_task(db_session, test_hotel, pre2, hk_a)
    await _room(db_session, test_hotel, "201")
    await _room(db_session, test_hotel, "202")

    r = await _import(
        client,
        test_hotel,
        manager_user,
        rooms=["201", "202"],
        housekeeper_ids=[str(hk_a.id), str(hk_b.id)],
    )

    assert r.status_code == 201
    assignments = {a["housekeeper_id"]: a["tasks_assigned"] for a in r.json()["assignments"]}
    assert assignments[str(hk_a.id)] == 0
    assert assignments[str(hk_b.id)] == 2


async def test_import_single_housekeeper_gets_all(
    client, db_session, test_hotel, manager_user
):
    await _room(db_session, test_hotel, "201")
    await _room(db_session, test_hotel, "202")
    hk = await _housekeeper(db_session, test_hotel, "solo@test.com", "Solo")

    r = await _import(
        client,
        test_hotel,
        manager_user,
        rooms=["201", "202"],
        housekeeper_ids=[str(hk.id)],
    )
    assert r.status_code == 201
    assert r.json()["assignments"][0]["tasks_assigned"] == 2


async def test_import_deduplicates_repeated_room_numbers(
    client, db_session, test_hotel, manager_user
):
    await _room(db_session, test_hotel, "201")
    r = await _import(
        client, test_hotel, manager_user, rooms=["201", "201", " 201 "]
    )
    assert r.status_code == 201
    assert r.json()["tasks_created"] == 1


# --- Explicit assignments (floor-map zone flow) -----------------------------


async def _tasks_by_room(client, hotel, manager):
    """room_number -> task dict, for asserting who each room went to."""
    rooms = (
        await client.get(
            f"/api/v1/hotels/{hotel.id}/rooms", headers=auth_headers(manager)
        )
    ).json()
    number_by_id = {r["id"]: r["room_number"] for r in rooms}
    tasks = (
        await client.get(
            f"/api/v1/hotels/{hotel.id}/tasks", headers=auth_headers(manager)
        )
    ).json()
    return {number_by_id[t["room_id"]]: t for t in tasks}


async def test_import_explicit_assignments_honored(
    client, db_session, test_hotel, manager_user
):
    # room1->A, room2->B, room3->A: honored verbatim, NOT even-split (which would
    # give each housekeeper a contiguous share by natural order).
    for n in ("201", "202", "203"):
        await _room(db_session, test_hotel, n)
    hk_a = await _housekeeper(db_session, test_hotel, "a@test.com", "Ann")
    hk_b = await _housekeeper(db_session, test_hotel, "b@test.com", "Bob")

    r = await _import(
        client,
        test_hotel,
        manager_user,
        assignments=[
            {"room_number": "201", "housekeeper_id": str(hk_a.id)},
            {"room_number": "202", "housekeeper_id": str(hk_b.id)},
            {"room_number": "203", "housekeeper_id": str(hk_a.id)},
        ],
    )

    assert r.status_code == 201
    body = r.json()
    assert body["tasks_created"] == 3
    assert body["rooms_set_dirty"] == 3
    counts = {a["housekeeper_id"]: a["tasks_assigned"] for a in body["assignments"]}
    assert counts == {str(hk_a.id): 2, str(hk_b.id): 1}

    by_room = await _tasks_by_room(client, test_hotel, manager_user)
    assert by_room["201"]["assigned_to"] == str(hk_a.id)
    assert by_room["202"]["assigned_to"] == str(hk_b.id)
    assert by_room["203"]["assigned_to"] == str(hk_a.id)
    assert all(t["status"] == "assigned" for t in by_room.values())


async def test_import_explicit_skips_still_apply(
    client, db_session, test_hotel, manager_user, housekeeper_user
):
    # An out-of-service room and one already carrying an open task are named in
    # the assignments but produce no new task; the clean room does.
    clean = await _room(db_session, test_hotel, "201")
    oos = await _room(
        db_session, test_hotel, "202", status=RoomStatus.OUT_OF_SERVICE
    )
    busy = await _room(db_session, test_hotel, "203")
    await _assigned_task(db_session, test_hotel, busy, housekeeper_user)
    hk = await _housekeeper(db_session, test_hotel, "a@test.com", "Ann")

    r = await _import(
        client,
        test_hotel,
        manager_user,
        assignments=[
            {"room_number": "201", "housekeeper_id": str(hk.id)},
            {"room_number": "202", "housekeeper_id": str(hk.id)},
            {"room_number": "203", "housekeeper_id": str(hk.id)},
        ],
    )

    assert r.status_code == 201
    body = r.json()
    assert body["tasks_created"] == 1
    reasons = {s["room_number"]: s["reason"] for s in body["skipped"]}
    assert reasons == {"202": "out_of_service", "203": "existing_open_task"}
    assert clean and oos  # (bind names for readability)


async def test_import_explicit_unknown_room_rejects_whole_batch(
    client, db_session, test_hotel, manager_user
):
    await _room(db_session, test_hotel, "201")
    hk = await _housekeeper(db_session, test_hotel, "a@test.com", "Ann")

    r = await _import(
        client,
        test_hotel,
        manager_user,
        assignments=[
            {"room_number": "201", "housekeeper_id": str(hk.id)},
            {"room_number": "999", "housekeeper_id": str(hk.id)},
        ],
    )
    assert r.status_code == 422
    assert r.json()["detail"]["errors"][0]["field"] == "rooms"
    # Nothing created.
    tasks = (
        await client.get(
            f"/api/v1/hotels/{test_hotel.id}/tasks",
            headers=auth_headers(manager_user),
        )
    ).json()
    assert tasks == []


async def test_import_explicit_non_housekeeper_rejected(
    client, db_session, test_hotel, manager_user
):
    await _room(db_session, test_hotel, "201")
    r = await _import(
        client,
        test_hotel,
        manager_user,
        assignments=[
            {"room_number": "201", "housekeeper_id": str(manager_user.id)},
        ],
    )
    assert r.status_code == 422
    assert r.json()["detail"]["errors"][0]["field"] == "housekeeper_ids"


async def test_import_explicit_cross_hotel_housekeeper_rejected(
    client, db_session, test_hotel, manager_user, other_hotel
):
    await _room(db_session, test_hotel, "201")
    foreign_hk = await _housekeeper(
        db_session, other_hotel, "foreign-hk@test.com", "Foreign HK"
    )
    r = await _import(
        client,
        test_hotel,
        manager_user,
        assignments=[
            {"room_number": "201", "housekeeper_id": str(foreign_hk.id)},
        ],
    )
    assert r.status_code == 422


# --- Mark dirty without creating tasks (assign-on-map later) -----------------


async def test_import_mark_dirty_only_creates_no_tasks(
    client, db_session, test_hotel, manager_user
):
    await _room(db_session, test_hotel, "201")
    await _room(db_session, test_hotel, "202", status=RoomStatus.OUT_OF_SERVICE)
    r = await _import(
        client, test_hotel, manager_user, rooms=["201", "202"], create_tasks=False
    )
    assert r.status_code == 201
    body = r.json()
    assert body["tasks_created"] == 0
    assert body["rooms_set_dirty"] == 1  # out-of-service still skipped
    assert body["assignments"] == []
    assert [s["reason"] for s in body["skipped"]] == ["out_of_service"]

    # No task created; room 201 is now dirty.
    tasks = (
        await client.get(
            f"/api/v1/hotels/{test_hotel.id}/tasks",
            headers=auth_headers(manager_user),
        )
    ).json()
    assert tasks == []
    rooms = (
        await client.get(
            f"/api/v1/hotels/{test_hotel.id}/rooms",
            headers=auth_headers(manager_user),
        )
    ).json()
    by_num = {r["room_number"]: r for r in rooms}
    assert by_num["201"]["status"] == "dirty"


async def test_import_mark_dirty_only_ignores_open_task_and_housekeepers(
    client, db_session, test_hotel, manager_user, housekeeper_user
):
    # A room already carrying an open task is NOT reported as skipped here (the
    # existing-open-task check only matters when creating tasks); it just stays
    # dirty. Housekeeper ids are ignored, not validated.
    busy = await _room(db_session, test_hotel, "201")
    await _assigned_task(db_session, test_hotel, busy, housekeeper_user)
    r = await _import(
        client,
        test_hotel,
        manager_user,
        rooms=["201"],
        housekeeper_ids=[str(uuid.uuid4())],  # bogus, but ignored
        create_tasks=False,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["tasks_created"] == 0
    assert body["rooms_set_dirty"] == 1
    assert body["skipped"] == []


async def test_import_mark_dirty_only_unknown_room_rejected(
    client, db_session, test_hotel, manager_user
):
    await _room(db_session, test_hotel, "201")
    r = await _import(
        client, test_hotel, manager_user, rooms=["201", "999"], create_tasks=False
    )
    assert r.status_code == 422
