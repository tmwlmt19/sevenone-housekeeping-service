import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import ShiftCloseReason


class ShiftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hotel_id: uuid.UUID
    housekeeper_id: uuid.UUID
    started_at: datetime
    ended_at: datetime | None
    close_reason: ShiftCloseReason | None
    assigned_count: int | None
    completed_count: int | None
    all_assigned_done: bool | None
    created_at: datetime
    updated_at: datetime


class CurrentShiftResponse(BaseModel):
    """The housekeeper's currently open shift, or null when they're off shift —
    the web app's clock-in gate reads this to decide whether to unlock work."""

    shift: ShiftRead | None
