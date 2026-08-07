import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import (
    get_current_user,
    require_manager_or_above,
    require_same_hotel,
)
from app.models.enums import RoomStatus, TaskStatus, UserRole
from app.models.hotel import Hotel
from app.models.room import Room
from app.models.task import Task
from app.models.user import User
from app.schemas.task import (
    ClearCompletedResponse,
    ReassignWorkload,
    RedistributeWorkload,
    TaskCreate,
    TaskRead,
    TaskStatusUpdate,
    TaskUpdate,
    WorkloadMoveResponse,
)
from app.schemas.task_import import (
    DirtyRoomImportRequest,
    DirtyRoomImportResponse,
)
from app.services import stats, workload
from app.services.task_import import import_dirty_rooms

router = APIRouter(prefix="/api/v1/hotels/{hotel_id}/tasks", tags=["tasks"])

# Roles that run hotel operations (can complete/approve tasks directly).
_MANAGER_ROLES = (UserRole.ADMIN, UserRole.MANAGER, UserRole.FRONT_DESK)


async def _get_task_in_hotel_or_404(
    db: AsyncSession, hotel_id: uuid.UUID, task_id: uuid.UUID
) -> Task:
    task = await db.get(Task, task_id)
    if task is None or task.hotel_id != hotel_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
        )
    return task


async def _validate_room(
    db: AsyncSession, hotel_id: uuid.UUID, room_id: uuid.UUID
) -> None:
    room = await db.get(Room, room_id)
    if room is None or room.hotel_id != hotel_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Room does not exist in this hotel",
        )


async def _validate_assignee(
    db: AsyncSession, hotel_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    user = await db.get(User, user_id)
    if user is None or user.hotel_id != hotel_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Assigned user does not exist in this hotel",
        )


# A task the housekeeper has finished working on (their part is done, whether or
# not a manager has approved it yet). Crossing INTO this set is a "clean finished"
# event; the pending_approval -> completed approval step stays within it.
_FINISHED_STATUSES = (TaskStatus.PENDING_APPROVAL, TaskStatus.COMPLETED)


async def _apply_status_side_effects(
    db: AsyncSession,
    task: Task,
    new_status: TaskStatus,
    *,
    old_status: TaskStatus,
    cleaned_by: uuid.UUID | None = None,
) -> None:
    """Keep started_at/completed_at, the room, and the stats rollups in sync with
    a task's status. `old_status` is the status before this change (callers pass
    it because the task object may or may not have been mutated yet).

    - First move to in_progress stamps started_at — the clean's clock start.
    - When the housekeeper *finishes* (submits for approval, or completes
      directly) we record the clean exactly once, timed at the finish rather than
      a later manager approval, so approval latency never inflates clean time.
    - Completion still marks the room clean and credits the housekeeper (the
      assignee, falling back to whoever completed it); non-completed statuses
      clear completed_at."""
    if new_status == TaskStatus.IN_PROGRESS and task.started_at is None:
        task.started_at = datetime.now(timezone.utc)

    if (
        new_status in _FINISHED_STATUSES
        and old_status not in _FINISHED_STATUSES
        and task.assigned_to is not None
    ):
        room = await db.get(Room, task.room_id)
        await stats.record_clean(
            db,
            hotel_id=task.hotel_id,
            housekeeper_id=task.assigned_to,
            room_type=room.room_type if room is not None else None,
            started_at=task.started_at,
            finished_at=datetime.now(timezone.utc),
        )

    if new_status == TaskStatus.COMPLETED and old_status != TaskStatus.COMPLETED:
        task.completed_at = datetime.now(timezone.utc)
        room = await db.get(Room, task.room_id)
        if room is not None:
            room.status = RoomStatus.CLEAN
            room.last_cleaned_by = task.assigned_to or cleaned_by
    elif new_status != TaskStatus.COMPLETED:
        task.completed_at = None


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(
    hotel_id: uuid.UUID,
    payload: TaskCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
) -> Task:
    require_same_hotel(hotel_id, current_user)
    await _validate_room(db, hotel_id, payload.room_id)
    if payload.assigned_to is not None:
        await _validate_assignee(db, hotel_id, payload.assigned_to)

    data = payload.model_dump()
    # If a task is created with an assignee but left pending, mark it assigned.
    if data["assigned_to"] is not None and data["status"] == TaskStatus.PENDING:
        data["status"] = TaskStatus.ASSIGNED

    task = Task(hotel_id=hotel_id, **data)
    # Apply side effects for the created state as a transition from "new" (a fresh
    # task is unfinished) — handles a task created straight to in_progress /
    # completed, and records the clean/completion if so.
    await _apply_status_side_effects(
        db, task, task.status, old_status=TaskStatus.PENDING, cleaned_by=current_user.id
    )
    if task.assigned_to is not None:
        await stats.record_assignments(
            db, hotel_id=hotel_id, housekeeper_id=task.assigned_to
        )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


@router.post("/reassign", response_model=WorkloadMoveResponse)
async def reassign_workload(
    hotel_id: uuid.UUID,
    payload: ReassignWorkload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
) -> dict:
    """Call-in: move every open task from one housekeeper to a single other one."""
    require_same_hotel(hotel_id, current_user)
    return await workload.reassign_all(
        db,
        hotel_id=hotel_id,
        from_id=payload.from_housekeeper_id,
        to_id=payload.to_housekeeper_id,
    )


@router.post("/redistribute", response_model=WorkloadMoveResponse)
async def redistribute_workload(
    hotel_id: uuid.UUID,
    payload: RedistributeWorkload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
) -> dict:
    """No-show: split one housekeeper's open tasks across the covering
    housekeepers — a chosen subset, or all the others when none are named."""
    require_same_hotel(hotel_id, current_user)
    return await workload.redistribute(
        db,
        hotel_id=hotel_id,
        from_id=payload.from_housekeeper_id,
        to_ids=payload.to_housekeeper_ids,
    )


@router.post("/clear-completed", response_model=ClearCompletedResponse)
async def clear_completed_tasks(
    hotel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
) -> ClearCompletedResponse:
    """Clear all completed tasks off the board. Soft-archive (sets archived_at),
    so the rows — and their 'last cleaned by' credit — are kept but hidden."""
    require_same_hotel(hotel_id, current_user)
    result = await db.execute(
        update(Task)
        .where(
            Task.hotel_id == hotel_id,
            Task.status == TaskStatus.COMPLETED,
            Task.archived_at.is_(None),
        )
        .values(archived_at=datetime.now(timezone.utc))
    )
    await db.commit()
    return ClearCompletedResponse(cleared=result.rowcount or 0)


@router.post(
    "/import",
    response_model=DirtyRoomImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_dirty_rooms_endpoint(
    hotel_id: uuid.UUID,
    payload: DirtyRoomImportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
) -> DirtyRoomImportResponse:
    """Bulk-import a list of dirty rooms (e.g. from a manager's CSV): set each
    room dirty, create a cleaning task per room, and either split the new tasks
    evenly across the chosen housekeepers or — when `assignments` is given (the
    floor-map zone flow) — honor an explicit room → housekeeper map. See the
    shared core in app/services/task_import.py for the full contract."""
    require_same_hotel(hotel_id, current_user)

    if payload.assignments is not None:
        # Explicit path: rooms + housekeepers come from the assignment map, and
        # the balancer is skipped. Pass every referenced housekeeper id as a ref
        # so they're validated/reported exactly like the even-split path.
        explicit = {a.room_number: a.housekeeper_id for a in payload.assignments}
        room_numbers = [a.room_number for a in payload.assignments]
        housekeeper_refs = [str(hk_id) for hk_id in dict.fromkeys(explicit.values())]
    else:
        explicit = None
        room_numbers = payload.rooms
        housekeeper_refs = [str(hk_id) for hk_id in payload.housekeeper_ids]

    summary = await import_dirty_rooms(
        db,
        hotel_id=hotel_id,
        room_numbers=room_numbers,
        housekeeper_refs=housekeeper_refs,
        resolve_mode="id",
        priority=payload.priority,
        create_tasks=payload.create_tasks,
        explicit_assignments=explicit,
    )
    return DirtyRoomImportResponse(**summary)


@router.get("", response_model=list[TaskRead])
async def list_tasks(
    hotel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    task_status: TaskStatus | None = Query(default=None, alias="status"),
    assigned_to: uuid.UUID | None = Query(default=None),
) -> list[Task]:
    require_same_hotel(hotel_id, current_user)
    # Cleared (archived) tasks are hidden from the board by default.
    query = select(Task).where(
        Task.hotel_id == hotel_id, Task.archived_at.is_(None)
    )
    if task_status is not None:
        query = query.where(Task.status == task_status)
    # Housekeepers may only ever see their own tasks, regardless of the filter.
    if current_user.role == UserRole.HOUSEKEEPER:
        query = query.where(Task.assigned_to == current_user.id)
    elif assigned_to is not None:
        query = query.where(Task.assigned_to == assigned_to)
    query = query.order_by(Task.created_at)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/{task_id}", response_model=TaskRead)
async def get_task(
    hotel_id: uuid.UUID,
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Task:
    require_same_hotel(hotel_id, current_user)
    task = await _get_task_in_hotel_or_404(db, hotel_id, task_id)
    # Housekeepers may only read tasks assigned to them.
    if (
        current_user.role == UserRole.HOUSEKEEPER
        and task.assigned_to != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
        )
    return task


@router.put("/{task_id}", response_model=TaskRead)
async def update_task(
    hotel_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: TaskUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
) -> Task:
    require_same_hotel(hotel_id, current_user)
    task = await _get_task_in_hotel_or_404(db, hotel_id, task_id)

    old_status = task.status
    old_assigned_to = task.assigned_to

    data = payload.model_dump(exclude_unset=True)
    if "room_id" in data:
        await _validate_room(db, hotel_id, data["room_id"])
    if data.get("assigned_to") is not None:
        await _validate_assignee(db, hotel_id, data["assigned_to"])

    # Apply field changes first so status side effects credit the *new* assignee.
    for field, value in data.items():
        setattr(task, field, value)

    if "status" in data:
        await _apply_status_side_effects(
            db, task, data["status"], old_status=old_status, cleaned_by=current_user.id
        )

    new_assigned_to = data.get("assigned_to")
    if new_assigned_to is not None and new_assigned_to != old_assigned_to:
        await stats.record_assignments(
            db, hotel_id=hotel_id, housekeeper_id=new_assigned_to
        )

    await db.commit()
    await db.refresh(task)
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    hotel_id: uuid.UUID,
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
) -> None:
    """Permanently delete a task. Manager/front-desk/admin only.

    Used by the edit-task modal's Delete button to drop a task created in error
    or no longer needed. Completed tasks are normally cleared (soft-archived via
    clear-completed) to keep their "last cleaned by" credit, but a room's credit
    lives on the room itself, so deleting the row outright is safe."""
    require_same_hotel(hotel_id, current_user)
    task = await _get_task_in_hotel_or_404(db, hotel_id, task_id)
    await db.delete(task)
    await db.commit()


@router.patch("/{task_id}/status", response_model=TaskRead)
async def update_task_status(
    hotel_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: TaskStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Task:
    """Update only a task's status.

    Allowed for managers/front-desk/admins, or the housekeeper the task is
    assigned to. Approval flow: when a housekeeper marks a task complete it goes
    to `pending_approval` for manager/front-desk sign-off, unless the hotel has
    `auto_approve_tasks` on (then it completes straight away). A task awaiting
    approval is out of the housekeeper's hands — only a manager can move it (to
    `completed` = approve, or back = reject)."""
    require_same_hotel(hotel_id, current_user)
    task = await _get_task_in_hotel_or_404(db, hotel_id, task_id)

    is_manager = current_user.role in _MANAGER_ROLES
    is_assignee = task.assigned_to == current_user.id
    if not (is_manager or is_assignee):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update status on tasks assigned to you",
        )

    # A submitted task is with the manager now; the housekeeper can't pull it back.
    if task.status == TaskStatus.PENDING_APPROVAL and not is_manager:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This task is awaiting manager approval",
        )

    new_status = payload.status
    # A housekeeper completing a task submits it for approval, unless the hotel
    # auto-approves. Managers/front-desk/admins complete (or approve) directly.
    if new_status == TaskStatus.COMPLETED and not is_manager:
        hotel = await db.get(Hotel, hotel_id)
        if hotel is not None and not hotel.auto_approve_tasks:
            new_status = TaskStatus.PENDING_APPROVAL

    old_status = task.status
    await _apply_status_side_effects(
        db, task, new_status, old_status=old_status, cleaned_by=current_user.id
    )
    task.status = new_status
    await db.commit()
    await db.refresh(task)
    return task
