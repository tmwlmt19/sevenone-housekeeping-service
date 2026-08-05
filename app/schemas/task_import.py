import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import TaskPriority

# Reasons a listed room produced no new task. Not errors — the import still
# succeeds; these are reported so the caller knows what was left alone.
SkipReason = Literal["existing_open_task", "out_of_service"]


class RoomAssignment(BaseModel):
    """One room handed to one housekeeper explicitly (the floor-map zone flow):
    the caller has already decided who cleans this room, so the even-split
    balancer is skipped for it."""

    room_number: str
    housekeeper_id: uuid.UUID


class DirtyRoomImportRequest(BaseModel):
    """Manager/CSV path: rooms and housekeepers are already in canonical form
    (plain room-number strings and housekeeper user IDs).

    Two assignment modes, mutually exclusive per request:
    - even-split: give `rooms` + `housekeeper_ids`; the balancer spreads the new
      tasks across the housekeepers.
    - explicit: give `assignments` (room → housekeeper); each room's task goes to
      the named housekeeper verbatim, no balancing. Powers both the map's manual
      zones and its client-side auto proximity-split, which produce the same
      explicit map. When present, `rooms`/`housekeeper_ids` are ignored.

    Set `create_tasks=false` to only mark the rooms dirty and create no tasks —
    the "assign on the map later" path: rooms go dirty now, then the manager
    groups them into cleaning tasks from the floor-map assign view. Housekeeper
    inputs are ignored in that case."""

    rooms: list[str] = Field(default_factory=list)
    housekeeper_ids: list[uuid.UUID] = Field(default_factory=list)
    assignments: list[RoomAssignment] | None = None
    create_tasks: bool = True
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
