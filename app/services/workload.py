"""Moving a housekeeper's open workload to other housekeepers.

Two operations, both hotel-ops actions (manager / front desk):

- **reassign** — move ALL of one housekeeper's open tasks to a single other
  housekeeper (a call-in: one person covers everything).
- **redistribute** — split one housekeeper's open tasks across a set of covering
  housekeepers, balancing by each one's current open load (a no-show). The set is
  either an explicit subset the caller names or, by default, all the hotel's
  *other* housekeepers.

The redistribute balancer is the same min-heap-by-load approach the bulk import
uses (`services/task_import.import_dirty_rooms`); kept here as a small local
helper so this feature doesn't depend on the import branch. If the two land
together, fold both onto one shared primitive.
"""

import heapq
import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TaskStatus, UserRole
from app.models.task import Task
from app.models.user import User

# Task states that count as "open" — the ones a housekeeper still has to do, and
# so the ones a reassign/redistribute moves. A pending_approval task is finished
# work sitting with a manager, not the housekeeper's to hand off.
OPEN_TASK_STATUSES = (
    TaskStatus.PENDING,
    TaskStatus.ASSIGNED,
    TaskStatus.IN_PROGRESS,
)


async def _get_hotel_housekeeper(
    db: AsyncSession, hotel_id: uuid.UUID, user_id: uuid.UUID, *, field: str
) -> User:
    user = await db.get(User, user_id)
    if user is None or user.hotel_id != hotel_id or user.role != UserRole.HOUSEKEEPER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field} is not a housekeeper in this hotel",
        )
    return user


async def _resolve_targets(
    db: AsyncSession,
    hotel_id: uuid.UUID,
    from_id: uuid.UUID,
    to_ids: list[uuid.UUID] | None,
) -> list[User]:
    """The housekeepers a redistribute spreads across. When `to_ids` is given,
    it's that explicit subset (each validated as a hotel housekeeper who isn't
    the one being covered, order-preserving-deduped); otherwise it's every other
    housekeeper in the hotel."""
    if to_ids:
        seen: set[uuid.UUID] = set()
        targets: list[User] = []
        for to_id in to_ids:
            if to_id == from_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot redistribute onto the housekeeper being covered",
                )
            if to_id in seen:
                continue
            seen.add(to_id)
            targets.append(
                await _get_hotel_housekeeper(
                    db, hotel_id, to_id, field="to_housekeeper_ids"
                )
            )
        return targets

    result = await db.execute(
        select(User).where(
            User.hotel_id == hotel_id,
            User.role == UserRole.HOUSEKEEPER,
            User.id != from_id,
        )
    )
    return list(result.scalars().all())


async def _open_tasks_assigned_to(
    db: AsyncSession, hotel_id: uuid.UUID, user_id: uuid.UUID
) -> list[Task]:
    result = await db.execute(
        select(Task).where(
            Task.hotel_id == hotel_id,
            Task.assigned_to == user_id,
            Task.status.in_(OPEN_TASK_STATUSES),
        )
    )
    return list(result.scalars().all())


async def _existing_open_counts(
    db: AsyncSession, hotel_id: uuid.UUID, housekeepers: list[User]
) -> dict[uuid.UUID, int]:
    """Current open-task count per housekeeper (before this move)."""
    if not housekeepers:
        return {}
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


def _assign(task: Task, housekeeper_id: uuid.UUID) -> None:
    """Hand a task to a housekeeper: whatever state it was in (assigned, or a
    half-done in_progress the caller can't finish), it becomes a fresh assignment
    for the new person."""
    task.assigned_to = housekeeper_id
    task.status = TaskStatus.ASSIGNED


def _summarize(
    housekeepers: list[User], counts: dict[uuid.UUID, int]
) -> list[dict[str, object]]:
    return [
        {
            "housekeeper_id": hk.id,
            "name": hk.name,
            "tasks_assigned": counts.get(hk.id, 0),
        }
        for hk in housekeepers
    ]


async def reassign_all(
    db: AsyncSession,
    *,
    hotel_id: uuid.UUID,
    from_id: uuid.UUID,
    to_id: uuid.UUID,
) -> dict[str, object]:
    """Move every open task from one housekeeper to another. Returns a summary."""
    if from_id == to_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose a different housekeeper to reassign to",
        )
    await _get_hotel_housekeeper(db, hotel_id, from_id, field="from_housekeeper_id")
    target = await _get_hotel_housekeeper(
        db, hotel_id, to_id, field="to_housekeeper_id"
    )

    tasks = await _open_tasks_assigned_to(db, hotel_id, from_id)
    for task in tasks:
        _assign(task, to_id)
    await db.commit()

    return {
        "tasks_moved": len(tasks),
        "assignments": _summarize(
            [target], {target.id: len(tasks)}
        ),
    }


async def redistribute(
    db: AsyncSession,
    *,
    hotel_id: uuid.UUID,
    from_id: uuid.UUID,
    to_ids: list[uuid.UUID] | None = None,
) -> dict[str, object]:
    """Split a housekeeper's open tasks across a set of covering housekeepers,
    balancing by each one's current open load. `to_ids` names who to spread
    across; omit it (or pass an empty list) to use *all* of the hotel's other
    housekeepers. Returns a summary."""
    await _get_hotel_housekeeper(db, hotel_id, from_id, field="from_housekeeper_id")

    others = await _resolve_targets(db, hotel_id, from_id, to_ids)
    if not others:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No other housekeepers in this hotel to redistribute to",
        )

    tasks = await _open_tasks_assigned_to(db, hotel_id, from_id)
    counts = {hk.id: 0 for hk in others}

    if tasks:
        existing = await _existing_open_counts(db, hotel_id, others)
        # Min-heap keyed by current load, then a stable tiebreak, so each task
        # goes to whoever currently has the least, evening out total workload.
        heap: list[tuple[int, tuple[str, str], User]] = [
            (existing[hk.id], (hk.name.lower(), str(hk.id)), hk) for hk in others
        ]
        heapq.heapify(heap)
        # Stable task order (by id) so the split is deterministic.
        for task in sorted(tasks, key=lambda t: str(t.id)):
            load, tiebreak, hk = heapq.heappop(heap)
            _assign(task, hk.id)
            counts[hk.id] += 1
            heapq.heappush(heap, (load + 1, tiebreak, hk))

    await db.commit()

    return {
        "tasks_moved": len(tasks),
        "assignments": _summarize(others, counts),
    }
