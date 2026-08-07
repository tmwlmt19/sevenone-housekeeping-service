import uuid
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from app.models.enums import RoomStatus
from app.services.floor_geometry import (
    MIN_POLYGON_AREA,
    is_simple_polygon,
    polygon_area,
    round_polygon,
    round_pt,
    within_coord_bounds,
)

# Extend this to add a decoration type — it's validated at the API and stored as
# varchar, so a new kind needs no DB migration (just a matching renderer).
DecorationKind = Literal["hall", "stairs", "elevator", "lobby", "label"]

# A vertex is an [x, y] point in float feet. Geometry is stored as absolute
# vertices — rotation is baked in — so a rectangle is just four right-angle points.
Vertex = tuple[float, float]


def _validate_polygon(v: list[Vertex]) -> list[Vertex]:
    """A filled shape: >= 3 vertices, finite + in-bounds, positive area, and
    simple (no crossing edges). Coordinates are rounded to 0.01 ft."""
    if len(v) < 3:
        raise ValueError("a polygon needs at least 3 vertices")
    if not within_coord_bounds([list(p) for p in v]):
        raise ValueError("vertex coordinates must be finite and within bounds")
    pts = round_polygon([list(p) for p in v])
    if polygon_area(pts) < MIN_POLYGON_AREA:
        raise ValueError("polygon area is too small")
    if not is_simple_polygon(pts):
        raise ValueError("polygon edges must not cross")
    return [(p[0], p[1]) for p in pts]


Polygon = Annotated[list[Vertex], AfterValidator(_validate_polygon)]


class DoorRef(BaseModel):
    """A room's door: which edge it sits on (index into the room's vertices) and
    where along that edge (`t`, 0..1). Edge-relative so the door stays glued to the
    wall as the room is moved, rotated, or resized. It's rendered as a short line
    on that wall and is only valid where the wall borders another object."""

    model_config = ConfigDict(from_attributes=True)

    edge: int = Field(ge=0)
    t: float = Field(ge=0, le=1)


class DecorationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: DecorationKind
    vertices: list[Vertex]
    label: str | None


class DecorationWrite(BaseModel):
    """A decoration to persist. Echo an existing decoration's `id` (from a prior
    GET) to update it in place and keep its identity; omit `id` for a new one.
    Any decoration on the floor not present in the payload is removed. A `label`
    carries a single anchor point; every other kind carries a filled polygon."""

    id: uuid.UUID | None = None
    kind: DecorationKind
    vertices: list[Vertex]
    label: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def _check_geometry(self) -> "DecorationWrite":
        if self.kind == "label":
            if len(self.vertices) < 1:
                raise ValueError("a label needs an anchor point")
            if not within_coord_bounds([list(p) for p in self.vertices]):
                raise ValueError("anchor coordinates must be finite and in bounds")
            self.vertices = [tuple(round_pt(list(p))) for p in self.vertices]
        else:
            self.vertices = _validate_polygon(self.vertices)
        return self


class PlacementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    vertices: list[Vertex]
    door: DoorRef | None = None


class PlacementWrite(BaseModel):
    """One room's footprint on the floor canvas as an absolute polygon (float
    feet), plus an optional edge-relative door for later path routing."""

    room_id: uuid.UUID
    vertices: Polygon
    door: DoorRef | None = None


class MapRoomRead(BaseModel):
    """A room as it appears on the map: identity + live status + where it sits
    (placement is null until the room has been placed). `has_open_task` flags a
    room that already carries a live cleaning task — the assign view uses it to
    exclude such rooms from the dirty-room candidates (same rule the import uses
    to skip them), so it never double-tasks a room."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    room_number: str
    room_type: str | None
    status: RoomStatus
    has_open_task: bool = False
    placement: PlacementRead | None


class FloorMapRead(BaseModel):
    """One floor's saved layout plus every room on that floor (placed or not).
    width/height are null for a floor that has rooms but no saved map yet; outline
    is null for a plain rectangular floor."""

    floor: int
    name: str | None
    width_ft: int | None
    height_ft: int | None
    grid_ft: int
    outline: list[Vertex] | None
    decorations: list[DecorationRead]
    rooms: list[MapRoomRead]


class HotelMapRead(BaseModel):
    floors: list[FloorMapRead]


class FloorMapWrite(BaseModel):
    """Full-floor save body: the floor's metadata, its outline polygon (null = a
    plain rectangle), its decorations (upserted by id, missing ones pruned), and
    the complete set of room placements for the floor (any room omitted becomes
    unplaced)."""

    name: str | None = Field(default=None, max_length=80)
    width_ft: int = Field(gt=0)
    height_ft: int = Field(gt=0)
    grid_ft: int = Field(default=1, ge=1)
    outline: Polygon | None = None
    decorations: list[DecorationWrite] = Field(default_factory=list)
    placements: list[PlacementWrite] = Field(default_factory=list)
