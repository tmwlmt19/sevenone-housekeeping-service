"""Shared core for bulk 'dirty room' task import.

Both entry points — the PMS JSON endpoint (API-key auth) and the manager CSV
endpoint (cookie auth) — resolve their inputs to `(room numbers, housekeeper
refs)` and call `import_dirty_rooms`, so the two paths can never diverge. The only
difference is how housekeepers are identified: by user ID (CSV) or by name (PMS).

Behavior (see docs/housekeeping/pms-task-import-plan.md):
- All-or-nothing validation: any unknown room number, or any unmatched/ambiguous
  housekeeper, fails the whole batch with every problem reported at once (422).
- Every listed, known room that isn't out-of-service is set to `dirty`.
- Rooms already carrying an open task are skipped (idempotent re-pushes); rooms
  that are out-of-service are skipped for tasking. Both are reported, not errors.
- New tasks are balance-assigned across the given housekeepers so each one's
  *total* open workload ends up as even as possible.
"""

import heapq
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import RoomStatus, TaskPriority, TaskStatus, UserRole
from app.models.room import Room
from app.models.task import Task
from app.models.user import User

# Task states that count as "open" — an open cleaning task makes a room a
# duplicate, and open tasks are what the balancer equalizes.
OPEN_TASK_STATUSES = (
    TaskStatus.PENDING,
    TaskStatus.ASSIGNED,
    TaskStatus.IN_PROGRESS,
)

ResolveMode = Literal["id", "name"]


def _natural_key(room_number: str) -> list[object]:
    """Numeric-aware sort key so '2' < '10' and assignment order is stable."""
    return [
        int(chunk) if chunk.isdigit() else chunk.lower()
        for chunk in re.split(r"(\d+)", room_number)
    ]


def _today_utc_midnight() -> datetime:
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


def _raise_validation(errors: list[dict[str, Any]]) -> None:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "message": (
                f"{len(errors)} problem(s) blocked the import. Nothing was "
                "created."
            ),
            "errors": errors,
        },
    )


async def _resolve_housekeepers(
    db: AsyncSession,
    hotel_id: uuid.UUID,
    refs: list[str],
    resolve_mode: ResolveMode,
    errors: list[dict[str, Any]],
) -> list[User]:
    """Resolve housekeeper references to distinct in-hotel housekeeper users.

    Appends to `errors` (rather than raising) so room and housekeeper problems
    are reported together. Preserves caller order and de-duplicates."""
    if not refs:
        return []

    result = await db.execute(
        select(User).where(
            User.hotel_id == hotel_id,
            User.role == UserRole.HOUSEKEEPER,
        )
    )
    housekeepers = list(result.scalars().all())
    by_id = {hk.id: hk for hk in housekeepers}
    by_name: dict[str, list[User]] = {}
    for hk in housekeepers:
        by_name.setdefault(hk.name.strip().lower(), []).append(hk)

    resolved: list[User] = []
    seen: set[uuid.UUID] = set()

    for ref in refs:
        match: User | None = None
        if resolve_mode == "id":
            try:
                user_id = uuid.UUID(str(ref))
            except (ValueError, TypeError):
                errors.append(
                    {
                        "field": "housekeeper_ids",
                        "value": ref,
                        "message": f"'{ref}' is not a valid user id",
                    }
                )
                continue
            match = by_id.get(user_id)
            if match is None:
                errors.append(
                    {
                        "field": "housekeeper_ids",
                        "value": str(ref),
                        "message": "Not a housekeeper in this hotel",
                    }
                )
                continue
        else:  # name
            candidates = by_name.get(ref.strip().lower(), [])
            if not candidates:
                errors.append(
                    {
                        "field": "housekeepers",
                        "value": ref,
                        "message": f"No housekeeper named '{ref}' in this hotel",
                    }
                )
                continue
            if len(candidates) > 1:
                errors.append(
                    {
                        "field": "housekeepers",
                        "value": ref,
                        "message": (
                            f"'{ref}' matches {len(candidates)} housekeepers; "
                            "use a unique name"
                        ),
                    }
                )
                continue
            match = candidates[0]

        if match.id not in seen:
            seen.add(match.id)
            resolved.append(match)

    return resolved


async def import_dirty_rooms(
    db: AsyncSession,
    *,
    hotel_id: uuid.UUID,
    room_numbers: list[str],
    housekeeper_refs: list[str],
    resolve_mode: ResolveMode,
    priority: TaskPriority = TaskPriority.NORMAL,
    seed_errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the import in a single transaction. Returns a summary dict shaped like
    DirtyRoomImportResponse. Raises 422 (all-or-nothing) on any hard error."""
    errors: list[dict[str, Any]] = list(seed_errors or [])

    # --- Normalize + de-duplicate the requested room numbers -----------------
    unique_numbers: list[str] = []
    seen_numbers: set[str] = set()
    for raw in room_numbers:
        number = raw.strip()
        if not number or number in seen_numbers:
            continue
        seen_numbers.add(number)
        unique_numbers.append(number)

    # --- Load the hotel's rooms and flag unknown numbers ---------------------
    result = await db.execute(select(Room).where(Room.hotel_id == hotel_id))
    rooms_by_number = {room.room_number: room for room in result.scalars().all()}

    known_rooms: list[Room] = []
    for number in unique_numbers:
        room = rooms_by_number.get(number)
        if room is None:
            errors.append(
                {
                    "field": "rooms",
                    "value": number,
                    "message": "No room with this number in this hotel",
                }
            )
        else:
            known_rooms.append(room)

    # --- Resolve housekeepers (collects into the same error list) ------------
    housekeepers = await _resolve_housekeepers(
        db, hotel_id, housekeeper_refs, resolve_mode, errors
    )

    if not unique_numbers and not errors:
        errors.append(
            {"field": "rooms", "value": None, "message": "No rooms to import"}
        )

    if errors:
        _raise_validation(errors)

    # --- Which known rooms already have an open task? ------------------------
    room_ids = [room.id for room in known_rooms]
    rooms_with_open_task: set[uuid.UUID] = set()
    if room_ids:
        result = await db.execute(
            select(Task.room_id).where(
                Task.hotel_id == hotel_id,
                Task.room_id.in_(room_ids),
                Task.status.in_(OPEN_TASK_STATUSES),
            )
        )
        rooms_with_open_task = set(result.scalars().all())

    # --- Set dirty, skip as needed, create the new tasks ---------------------
    skipped: list[dict[str, Any]] = []
    rooms_set_dirty = 0
    due_date = _today_utc_midnight()
    new_tasks: list[tuple[Task, str]] = []  # (task, room_number) for stable order

    for room in known_rooms:
        if room.status == RoomStatus.OUT_OF_SERVICE:
            skipped.append(
                {"room_number": room.room_number, "reason": "out_of_service"}
            )
            continue

        room.status = RoomStatus.DIRTY
        rooms_set_dirty += 1

        if room.id in rooms_with_open_task:
            skipped.append(
                {"room_number": room.room_number, "reason": "existing_open_task"}
            )
            continue

        task = Task(
            hotel_id=hotel_id,
            room_id=room.id,
            status=TaskStatus.PENDING,
            priority=priority,
            due_date=due_date,
        )
        new_tasks.append((task, room.room_number))

    # --- Balance-assign across housekeepers ----------------------------------
    assignment_counts = {hk.id: 0 for hk in housekeepers}
    if housekeepers and new_tasks:
        existing_load = await _existing_open_counts(db, hotel_id, housekeepers)
        # Min-heap keyed by current load, then a stable unique tiebreak.
        heap: list[tuple[int, tuple[str, str], User]] = [
            (existing_load[hk.id], (hk.name.lower(), str(hk.id)), hk)
            for hk in housekeepers
        ]
        heapq.heapify(heap)
        for task, _room_number in sorted(new_tasks, key=lambda e: _natural_key(e[1])):
            load, tiebreak, hk = heapq.heappop(heap)
            task.assigned_to = hk.id
            task.status = TaskStatus.ASSIGNED
            assignment_counts[hk.id] += 1
            heapq.heappush(heap, (load + 1, tiebreak, hk))

    db.add_all([task for task, _ in new_tasks])
    await db.commit()

    return {
        "rooms_set_dirty": rooms_set_dirty,
        "tasks_created": len(new_tasks),
        "skipped": skipped,
        "assignments": [
            {
                "housekeeper_id": hk.id,
                "name": hk.name,
                "tasks_assigned": assignment_counts[hk.id],
            }
            for hk in housekeepers
        ],
    }


async def _existing_open_counts(
    db: AsyncSession, hotel_id: uuid.UUID, housekeepers: list[User]
) -> dict[uuid.UUID, int]:
    """Current open-task count per housekeeper, before this batch."""
    result = await db.execute(
        select(Task.assigned_to, func.count())
        .where(
            Task.hotel_id == hotel_id,
            Task.assigned_to.in_([hk.id for hk in housekeepers]),
            Task.status.in_(OPEN_TASK_STATUSES),
        )
        .group_by(Task.assigned_to)
    )
    counts = {row[0]: row[1] for row in result.all()}
    return {hk.id: counts.get(hk.id, 0) for hk in housekeepers}
