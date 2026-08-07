import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import TaskPriority, TaskStatus


class TaskCreate(BaseModel):
    room_id: uuid.UUID
    assigned_to: uuid.UUID | None = None
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.NORMAL
    notes: str | None = None
    due_date: datetime | None = None


class TaskUpdate(BaseModel):
    room_id: uuid.UUID | None = None
    assigned_to: uuid.UUID | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    notes: str | None = None
    due_date: datetime | None = None


class TaskStatusUpdate(BaseModel):
    status: TaskStatus


class ReassignWorkload(BaseModel):
    """Move ALL of one housekeeper's open tasks to a single other housekeeper
    (a call-in: the first housekeeper is out, one person covers everything)."""

    from_housekeeper_id: uuid.UUID
    to_housekeeper_id: uuid.UUID


class RedistributeWorkload(BaseModel):
    """Split one housekeeper's open tasks across a set of covering housekeepers
    (a no-show: spread the load rather than dump it on one person).

    `to_housekeeper_ids` names who to spread across; omit it (or send an empty
    list) to spread across *all* of the hotel's other housekeepers. Naming a
    single housekeeper hands them everything — the same effect as a reassign."""

    from_housekeeper_id: uuid.UUID
    to_housekeeper_ids: list[uuid.UUID] | None = None


class WorkloadAssignment(BaseModel):
    housekeeper_id: uuid.UUID
    name: str
    tasks_assigned: int


class WorkloadMoveResponse(BaseModel):
    """Summary of a reassign/redistribute: how many open tasks moved and how many
    each receiving housekeeper ended up with."""

    tasks_moved: int
    assignments: list[WorkloadAssignment]


class ClearCompletedResponse(BaseModel):
    """How many completed tasks were cleared (soft-archived) off the board."""

    cleared: int


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hotel_id: uuid.UUID
    room_id: uuid.UUID
    assigned_to: uuid.UUID | None
    status: TaskStatus
    priority: TaskPriority
    notes: str | None
    due_date: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
