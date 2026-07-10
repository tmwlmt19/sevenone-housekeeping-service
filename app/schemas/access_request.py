import uuid
from datetime import datetime
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from app.models.enums import (
    RequestKind,
    RequestResource,
    RequestStatus,
    RoomStatus,
    UserRole,
)
from app.schemas.room import _normalize_room_type

# Roles a manager may request to add. Admin is a platform-level role and is
# never created through a tenant's staff request.
_REQUESTABLE_ROLES = {UserRole.MANAGER, UserRole.HOUSEKEEPER}


class StaffAddPayload(BaseModel):
    """Proposed staff member for a `staff`/`add` request. No password: a temp
    password is generated at approval time and shown once to the admin."""

    email: EmailStr
    name: str = Field(min_length=1, max_length=255)
    role: UserRole

    @field_validator("role")
    @classmethod
    def _role_is_requestable(cls, value: UserRole) -> UserRole:
        if value not in _REQUESTABLE_ROLES:
            raise ValueError("Role must be manager or housekeeper")
        return value


class RoomAddPayload(BaseModel):
    """Proposed room for a `room`/`add` request."""

    room_number: str = Field(min_length=1, max_length=50)
    floor: int | None = None
    room_type: str | None = Field(default=None, max_length=20)
    status: RoomStatus = RoomStatus.CLEAN

    _norm_type = field_validator("room_type")(_normalize_room_type)


class AccessRequestCreate(BaseModel):
    """A manager files this. `add` requires a resource-matched `payload` and no
    `target_id`; `remove` requires a `target_id` and no `payload`."""

    resource: RequestResource
    kind: RequestKind
    note: str | None = Field(default=None, max_length=1000)
    target_id: uuid.UUID | None = None
    payload: StaffAddPayload | RoomAddPayload | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> "AccessRequestCreate":
        if self.kind is RequestKind.ADD:
            if self.payload is None:
                raise ValueError("payload is required for add requests")
            if self.target_id is not None:
                raise ValueError("target_id must be omitted for add requests")
            staff_ok = self.resource is RequestResource.STAFF and isinstance(
                self.payload, StaffAddPayload
            )
            room_ok = self.resource is RequestResource.ROOM and isinstance(
                self.payload, RoomAddPayload
            )
            if not (staff_ok or room_ok):
                raise ValueError("payload does not match the requested resource")
        else:  # REMOVE
            if self.target_id is None:
                raise ValueError("target_id is required for remove requests")
            if self.payload is not None:
                raise ValueError("payload must be omitted for remove requests")
        return self


class AccessRequestReject(BaseModel):
    decision_note: str | None = Field(default=None, max_length=1000)


class AccessRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hotel_id: uuid.UUID
    resource: RequestResource
    kind: RequestKind
    status: RequestStatus
    requested_by: uuid.UUID | None
    target_id: uuid.UUID | None
    payload: dict[str, Any] | None
    note: str | None
    decision_note: str | None
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AccessRequestDecision(BaseModel):
    """Returned when an admin approves a request. For a staff `add`, the one-time
    temp password and the created user are surfaced so the admin can hand them
    over; other kinds return just the closed request."""

    request: AccessRequestRead
    temporary_password: str | None = None
