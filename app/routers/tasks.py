import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import (
    get_current_user,
    require_manager_or_above,
    require_same_hotel,
)
from app.models.enums import RoomStatus, TaskStatus, UserRole
from app.models.room import Room
from app.models.task import Task
from app.models.user import User
from app.schemas.task import TaskCreate, TaskRead, TaskStatusUpdate, TaskUpdate
from app.schemas.task_import import (
    DirtyRoomImportRequest,
    DirtyRoomImportResponse,
)
from app.services.task_import import import_dirty_rooms

router = APIRouter(prefix="/api/v1/hotels/{hotel_id}/tasks", tags=["tasks"])


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


async def _apply_completion_side_effects(
    db: AsyncSession, task: Task, new_status: TaskStatus
) -> None:
    """Keep completed_at and the room's status in sync with task status."""
    if new_status == TaskStatus.COMPLETED and task.status != TaskStatus.COMPLETED:
        task.completed_at = datetime.now(timezone.utc)
        room = await db.get(Room, task.room_id)
        if room is not None:
            room.status = RoomStatus.CLEAN
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
    if task.status == TaskStatus.COMPLETED:
        await _apply_completion_side_effects(db, task, TaskStatus.COMPLETED)
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


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
    room dirty, create a cleaning task per room, and optionally split the new
    tasks evenly across the chosen housekeepers. See the shared core in
    app/services/task_import.py for the full contract."""
    require_same_hotel(hotel_id, current_user)
    summary = await import_dirty_rooms(
        db,
        hotel_id=hotel_id,
        room_numbers=payload.rooms,
        housekeeper_refs=[str(hk_id) for hk_id in payload.housekeeper_ids],
        resolve_mode="id",
        priority=payload.priority,
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
    query = select(Task).where(Task.hotel_id == hotel_id)
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

    data = payload.model_dump(exclude_unset=True)
    if "room_id" in data:
        await _validate_room(db, hotel_id, data["room_id"])
    if data.get("assigned_to") is not None:
        await _validate_assignee(db, hotel_id, data["assigned_to"])

    if "status" in data:
        await _apply_completion_side_effects(db, task, data["status"])
    for field, value in data.items():
        setattr(task, field, value)

    await db.commit()
    await db.refresh(task)
    return task


@router.patch("/{task_id}/status", response_model=TaskRead)
async def update_task_status(
    hotel_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: TaskStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Task:
    """Update only a task's status. Allowed for managers/admins, or the
    housekeeper the task is assigned to."""
    require_same_hotel(hotel_id, current_user)
    task = await _get_task_in_hotel_or_404(db, hotel_id, task_id)

    is_manager = current_user.role in (UserRole.ADMIN, UserRole.MANAGER)
    is_assignee = task.assigned_to == current_user.id
    if not (is_manager or is_assignee):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update status on tasks assigned to you",
        )

    await _apply_completion_side_effects(db, task, payload.status)
    task.status = payload.status
    await db.commit()
    await db.refresh(task)
    return task
