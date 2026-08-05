import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import RoomStatus


def _normalize_room_type(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    return normalized or None


class RoomCreate(BaseModel):
    room_number: str = Field(min_length=1, max_length=50)
    floor: int | None = None
    # Short code (e.g. "STD", "STE", "DLX"); free-form so hotels can define
    # their own types. Normalized to uppercase.
    room_type: str | None = Field(default=None, max_length=20)
    status: RoomStatus = RoomStatus.CLEAN

    _norm_type = field_validator("room_type")(_normalize_room_type)


class RoomUpdate(BaseModel):
    room_number: str | None = Field(default=None, min_length=1, max_length=50)
    floor: int | None = None
    room_type: str | None = Field(default=None, max_length=20)
    status: RoomStatus | None = None

    _norm_type = field_validator("room_type")(_normalize_room_type)


class RoomStatusUpdate(BaseModel):
    """Status-only update. Managers may change a room's status without the
    full-edit (add/rename/delete) rights reserved for platform admins."""

    status: RoomStatus


class RoomRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hotel_id: uuid.UUID
    room_number: str
    floor: int | None
    room_type: str | None
    status: RoomStatus
    last_cleaned_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
