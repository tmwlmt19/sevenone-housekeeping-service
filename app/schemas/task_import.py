import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import TaskPriority

# Reasons a listed room produced no new task. Not errors — the import still
# succeeds; these are reported so the caller knows what was left alone.
SkipReason = Literal["existing_open_task", "out_of_service"]


class DirtyRoomImportRequest(BaseModel):
    """Manager/CSV path: rooms and housekeepers are already in canonical form
    (plain room-number strings and housekeeper user IDs)."""

    rooms: list[str] = Field(default_factory=list)
    housekeeper_ids: list[uuid.UUID] = Field(default_factory=list)
    priority: TaskPriority = TaskPriority.NORMAL


class PmsDirtyRoomsRequest(BaseModel):
    """PMS path: deliberately permissive. `rooms` may be plain strings or objects
    carrying a room number under any accepted alias; `housekeepers` are names.
    The default adapter (app.services.pms_adapters) normalizes this."""

    model_config = ConfigDict(extra="ignore")

    rooms: list[Any] = Field(default_factory=list)
    housekeepers: list[Any] = Field(default_factory=list)
    priority: TaskPriority = TaskPriority.NORMAL


class ImportSkip(BaseModel):
    room_number: str
    reason: SkipReason


class ImportAssignment(BaseModel):
    housekeeper_id: uuid.UUID
    name: str
    tasks_assigned: int


class DirtyRoomImportResponse(BaseModel):
    rooms_set_dirty: int
    tasks_created: int
    skipped: list[ImportSkip]
    assignments: list[ImportAssignment]
