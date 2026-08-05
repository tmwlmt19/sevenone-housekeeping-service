import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import RoomStatus

# Layout geometry is integer feet ("nearest foot"); rotation is 90° steps in v1.
_ROTATIONS = (0, 90, 180, 270)

# Extend this to add a decoration type — it's validated at the API and stored as
# varchar, so a new kind needs no DB migration (just a matching renderer).
DecorationKind = Literal["hall", "stairs", "elevator", "lobby", "label"]


class DecorationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: DecorationKind
    x: int
    y: int
    w: int
    h: int
    label: str | None


class DecorationWrite(BaseModel):
    """A decoration to persist. Echo an existing decoration's `id` (from a prior
    GET) to update it in place and keep its identity; omit `id` for a new one.
    Any decoration on the floor not present in the payload is removed."""

    id: uuid.UUID | None = None
    kind: DecorationKind
    x: int
    y: int
    # A label may have a zero footprint (anchored text), so w/h allow 0.
    w: int = Field(ge=0)
    h: int = Field(ge=0)
    label: str | None = Field(default=None, max_length=80)


class PlacementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    x: int
    y: int
    w: int
    h: int
    rotation: int


class PlacementWrite(BaseModel):
    """One room's footprint on the floor canvas, in integer feet."""

    room_id: uuid.UUID
    x: int
    y: int
    w: int = Field(gt=0)
    h: int = Field(gt=0)
    rotation: int = 0

    @field_validator("rotation")
    @classmethod
    def _check_rotation(cls, v: int) -> int:
        if v not in _ROTATIONS:
            raise ValueError("rotation must be one of 0, 90, 180, 270")
        return v


class MapRoomRead(BaseModel):
    """A room as it appears on the map: identity + live status + where it sits
    (placement is null until the room has been placed)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    room_number: str
    room_type: str | None
    status: RoomStatus
    placement: PlacementRead | None


class FloorMapRead(BaseModel):
    """One floor's saved layout plus every room on that floor (placed or not).
    width/height are null for a floor that has rooms but no saved map yet."""

    floor: int
    name: str | None
    width_ft: int | None
    height_ft: int | None
    grid_ft: int
    decorations: list[DecorationRead]
    rooms: list[MapRoomRead]


class HotelMapRead(BaseModel):
    floors: list[FloorMapRead]


class FloorMapWrite(BaseModel):
    """Full-floor save body: the floor's metadata, its decorations (upserted by
    id, missing ones pruned), and the complete set of room placements for the
    floor (any room omitted becomes unplaced)."""

    name: str | None = Field(default=None, max_length=80)
    width_ft: int = Field(gt=0)
    height_ft: int = Field(gt=0)
    grid_ft: int = Field(default=1, ge=1)
    decorations: list[DecorationWrite] = Field(default_factory=list)
    placements: list[PlacementWrite] = Field(default_factory=list)
