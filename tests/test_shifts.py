"""Housekeeper shifts: clock-in gate, clock-out == logout, stale-reclock
safeguard, and the efficiency snapshot + daily rollup written at close.
"""

import uuid

from sqlalchemy import select

from conftest import auth_headers

from app.models.enums import ShiftCloseReason
from app.models.shift import Shift
from app.models.stats import HousekeeperDailyStats


def _shifts_url(hotel, path: str = "") -> str:
    return f"/api/v1/hotels/{hotel.id}/shifts{path}"


def _status_url(hotel, task) -> str:
    return f"/api/v1/hotels/{hotel.id}/tasks/{task.id}/status"


async def test_clock_in_opens_shift_and_current_reflects_it(
    client, test_hotel, housekeeper_user
):
    r = await client.post(
        _shifts_url(test_hotel, "/clock-in"), headers=auth_headers(housekeeper_user)
    )
    assert r.status_code == 201
    body = r.json()
    assert body["housekeeper_id"] == str(housekeeper_user.id)
    assert body["ended_at"] is None

    r2 = await client.get(
        _shifts_url(test_hotel, "/current"), headers=auth_headers(housekeeper_user)
    )
    assert r2.status_code == 200
    assert r2.json()["shift"]["id"] == body["id"]


async def test_current_is_null_when_off_shift(client, test_hotel, housekeeper_user):
    r = await client.get(
        _shifts_url(test_hotel, "/current"), headers=auth_headers(housekeeper_user)
    )
    assert r.status_code == 200
    assert r.json()["shift"] is None


async def test_only_housekeepers_clock_in(client, test_hotel, manager_user):
    r = await client.post(
        _shifts_url(test_hotel, "/clock-in"), headers=auth_headers(manager_user)
    )
    assert r.status_code == 403


async def test_clock_in_again_closes_stale_shift(
    client, db_session, test_hotel, housekeeper_user
):
    r1 = await client.post(
        _shifts_url(test_hotel, "/clock-in"), headers=auth_headers(housekeeper_user)
    )
    first_id = uuid.UUID(r1.json()["id"])

    r2 = await client.post(
        _shifts_url(test_hotel, "/clock-in"), headers=auth_headers(housekeeper_user)
    )
    assert r2.status_code == 201
    assert r2.json()["id"] != str(first_id)

    first = await db_session.get(Shift, first_id)
    await db_session.refresh(first)
    assert first.ended_at is not None
    assert first.close_reason == ShiftCloseReason.STALE_RECLOCK

    open_shifts = (
        await db_session.execute(
            select(Shift).where(
                Shift.housekeeper_id == housekeeper_user.id,
                Shift.ended_at.is_(None),
            )
        )
    ).scalars().all()
    assert len(open_shifts) == 1


async def test_clock_out_when_off_shift_is_noop(
    client, test_hotel, housekeeper_user
):
    r = await client.post(
        _shifts_url(test_hotel, "/clock-out"), headers=auth_headers(housekeeper_user)
    )
    assert r.status_code == 200
    assert r.json()["shift"] is None


async def test_clock_out_snapshots_efficiency_and_rolls_up(
    client, db_session, test_hotel, test_task, housekeeper_user
):
    # Auto-approve so the housekeeper's completion lands as `completed` directly.
    test_hotel.auto_approve_tasks = True
    await db_session.flush()

    await client.post(
        _shifts_url(test_hotel, "/clock-in"), headers=auth_headers(housekeeper_user)
    )
    await client.patch(
        _status_url(test_hotel, test_task),
        headers=auth_headers(housekeeper_user),
        json={"status": "in_progress"},
    )
    await client.patch(
        _status_url(test_hotel, test_task),
        headers=auth_headers(housekeeper_user),
        json={"status": "completed"},
    )

    r = await client.post(
        _shifts_url(test_hotel, "/clock-out"), headers=auth_headers(housekeeper_user)
    )
    assert r.status_code == 200
    shift = r.json()["shift"]
    assert shift["ended_at"] is not None
    assert shift["close_reason"] == "logout"
    assert shift["assigned_count"] == 1
    assert shift["completed_count"] == 1
    assert shift["all_assigned_done"] is True

    row = (
        await db_session.execute(
            select(HousekeeperDailyStats).where(
                HousekeeperDailyStats.housekeeper_id == housekeeper_user.id
            )
        )
    ).scalar_one()
    assert row.shifts_count == 1
    assert row.shifts_worked == 1
    assert row.shifts_all_done == 1
    assert row.shift_seconds_total >= 0


async def test_logout_closes_open_shift(
    client, db_session, test_hotel, housekeeper_user
):
    r1 = await client.post(
        _shifts_url(test_hotel, "/clock-in"), headers=auth_headers(housekeeper_user)
    )
    shift_id = uuid.UUID(r1.json()["id"])

    r = await client.post(
        "/api/v1/auth/logout", headers=auth_headers(housekeeper_user)
    )
    assert r.status_code == 204

    shift = await db_session.get(Shift, shift_id)
    await db_session.refresh(shift)
    assert shift.ended_at is not None
    assert shift.close_reason == ShiftCloseReason.LOGOUT


async def test_clock_in_is_tenant_scoped(
    client, other_hotel, housekeeper_user
):
    # A housekeeper can't clock in against a hotel that isn't theirs.
    r = await client.post(
        _shifts_url(other_hotel, "/clock-in"), headers=auth_headers(housekeeper_user)
    )
    assert r.status_code == 404
