import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import (
    require_layout_editor,
    require_layout_viewer,
    require_same_hotel,
)
from app.models.floor_map import FloorDecoration, FloorMap, RoomPlacement
from app.models.room import Room
from app.models.user import User
from app.schemas.floor_map import (
    DecorationRead,
    FloorMapRead,
    FloorMapWrite,
    HotelMapRead,
    MapRoomRead,
    PlacementRead,
)

# Nested under a hotel like the other hotel-scoped resources. Layout is a third
# "scoped write" alongside room status and access requests — see hotel-map-plan.md.
router = APIRouter(prefix="/api/v1/hotels/{hotel_id}", tags=["floor-maps"])


def _map_room(room: Room, placement: RoomPlacement | None) -> MapRoomRead:
    return MapRoomRead(
        id=room.id,
        room_number=room.room_number,
        room_type=room.room_type,
        status=room.status,
        placement=(
            PlacementRead.model_validate(placement)
            if placement is not None
            else None
        ),
    )


async def _rooms_on_floor(
    db: AsyncSession, hotel_id: uuid.UUID, floor: int
) -> list[MapRoomRead]:
    """All rooms on one floor with their (optional) placement, ordered by number."""
    result = await db.execute(
        select(Room, RoomPlacement)
        .outerjoin(RoomPlacement, RoomPlacement.room_id == Room.id)
        .where(Room.hotel_id == hotel_id, Room.floor == floor)
        .order_by(Room.room_number)
    )
    return [_map_room(room, placement) for room, placement in result.all()]


async def _decorations_of(
    db: AsyncSession, floor_map_id: uuid.UUID
) -> list[DecorationRead]:
    result = await db.execute(
        select(FloorDecoration)
        .where(FloorDecoration.floor_map_id == floor_map_id)
        .order_by(FloorDecoration.created_at, FloorDecoration.id)
    )
    return [DecorationRead.model_validate(d) for d in result.scalars().all()]


@router.get("/map", response_model=HotelMapRead)
async def get_hotel_map(
    hotel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_layout_viewer),
) -> HotelMapRead:
    """Whole-hotel map in one payload: one entry per floor that has a saved
    layout or any room, each listing that floor's rooms with their placement
    (null = unplaced) and its decorations. Floor switching is then instant
    client-side. Rooms with no floor are excluded — they can't sit on a floor
    canvas until assigned one."""
    require_same_hotel(hotel_id, current_user)

    maps_result = await db.execute(
        select(FloorMap).where(FloorMap.hotel_id == hotel_id)
    )
    floor_maps = {fm.floor: fm for fm in maps_result.scalars().all()}

    # All decorations for this hotel's floor maps in one query, grouped by map.
    decorations_by_map: dict[uuid.UUID, list[DecorationRead]] = {}
    if floor_maps:
        dec_result = await db.execute(
            select(FloorDecoration)
            .where(
                FloorDecoration.floor_map_id.in_(
                    [fm.id for fm in floor_maps.values()]
                )
            )
            .order_by(FloorDecoration.created_at, FloorDecoration.id)
        )
        for d in dec_result.scalars().all():
            decorations_by_map.setdefault(d.floor_map_id, []).append(
                DecorationRead.model_validate(d)
            )

    # LEFT JOIN so unplaced rooms come back too; skip rooms with no floor.
    rooms_result = await db.execute(
        select(Room, RoomPlacement)
        .outerjoin(RoomPlacement, RoomPlacement.room_id == Room.id)
        .where(Room.hotel_id == hotel_id, Room.floor.is_not(None))
        .order_by(Room.floor, Room.room_number)
    )
    rooms_by_floor: dict[int, list[MapRoomRead]] = {}
    for room, placement in rooms_result.all():
        rooms_by_floor.setdefault(room.floor, []).append(
            _map_room(room, placement)
        )

    floors = sorted(set(floor_maps) | set(rooms_by_floor))
    return HotelMapRead(
        floors=[
            FloorMapRead(
                floor=floor,
                name=floor_maps[floor].name if floor in floor_maps else None,
                width_ft=(
                    floor_maps[floor].width_ft if floor in floor_maps else None
                ),
                height_ft=(
                    floor_maps[floor].height_ft if floor in floor_maps else None
                ),
                grid_ft=floor_maps[floor].grid_ft if floor in floor_maps else 1,
                decorations=(
                    decorations_by_map.get(floor_maps[floor].id, [])
                    if floor in floor_maps
                    else []
                ),
                rooms=rooms_by_floor.get(floor, []),
            )
            for floor in floors
        ]
    )


@router.put("/map/{floor}", response_model=FloorMapRead)
async def put_floor_map(
    hotel_id: uuid.UUID,
    floor: int,
    payload: FloorMapWrite,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_layout_editor),
) -> FloorMapRead:
    """Atomically save one floor: upsert its floor_maps metadata, upsert its
    decorations (by id, pruning any omitted), and replace the full set of room
    placements on the floor. Every placement's room must exist, belong to this
    hotel, and sit on this floor; any room on the floor omitted from the body has
    its placement removed. Room identity/status is untouched."""
    require_same_hotel(hotel_id, current_user)

    # Validate placement targets before mutating anything.
    room_ids = [p.room_id for p in payload.placements]
    rooms: dict[uuid.UUID, Room] = {}
    if room_ids:
        rooms_result = await db.execute(
            select(Room).where(Room.id.in_(room_ids))
        )
        rooms = {room.id: room for room in rooms_result.scalars().all()}
    for placement in payload.placements:
        room = rooms.get(placement.room_id)
        if room is None or room.hotel_id != hotel_id or room.floor != floor:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Room {placement.room_id} is not on floor {floor} "
                    "of this hotel"
                ),
            )

    # Upsert the floor_maps row; flush so a new map has an id for decoration FKs.
    fm_result = await db.execute(
        select(FloorMap).where(
            FloorMap.hotel_id == hotel_id, FloorMap.floor == floor
        )
    )
    floor_map = fm_result.scalar_one_or_none()
    if floor_map is None:
        floor_map = FloorMap(hotel_id=hotel_id, floor=floor)
        db.add(floor_map)
    floor_map.name = payload.name
    floor_map.width_ft = payload.width_ft
    floor_map.height_ft = payload.height_ft
    floor_map.grid_ft = payload.grid_ft
    await db.flush()

    # Decorations: upsert by id so a decoration keeps its identity across saves
    # (a future cleaning task can reference it); anything omitted is pruned. An
    # unknown/absent id is treated as a new decoration (server assigns the id).
    existing_result = await db.execute(
        select(FloorDecoration).where(
            FloorDecoration.floor_map_id == floor_map.id
        )
    )
    existing = {d.id: d for d in existing_result.scalars().all()}
    seen: set[uuid.UUID] = set()
    for item in payload.decorations:
        deco = existing.get(item.id) if item.id is not None else None
        if deco is not None:
            deco.kind = item.kind
            deco.x, deco.y, deco.w, deco.h = item.x, item.y, item.w, item.h
            deco.label = item.label
            seen.add(deco.id)
        else:
            db.add(
                FloorDecoration(
                    floor_map_id=floor_map.id,
                    kind=item.kind,
                    x=item.x,
                    y=item.y,
                    w=item.w,
                    h=item.h,
                    label=item.label,
                )
            )
    for deco_id, deco in existing.items():
        if deco_id not in seen:
            await db.delete(deco)

    # Full-floor replace of placements: drop every placement for rooms on this
    # floor, then insert the provided set. room_id is the stable natural key, so
    # re-placing the same room preserves the reference; the delete runs
    # immediately, so it can't trip the room_id primary key on re-insert.
    floor_room_ids = select(Room.id).where(
        Room.hotel_id == hotel_id, Room.floor == floor
    )
    await db.execute(
        delete(RoomPlacement).where(RoomPlacement.room_id.in_(floor_room_ids))
    )
    for placement in payload.placements:
        db.add(
            RoomPlacement(
                room_id=placement.room_id,
                x=placement.x,
                y=placement.y,
                w=placement.w,
                h=placement.h,
                rotation=placement.rotation,
            )
        )

    await db.commit()
    await db.refresh(floor_map)
    return FloorMapRead(
        floor=floor_map.floor,
        name=floor_map.name,
        width_ft=floor_map.width_ft,
        height_ft=floor_map.height_ft,
        grid_ft=floor_map.grid_ft,
        decorations=await _decorations_of(db, floor_map.id),
        rooms=await _rooms_on_floor(db, hotel_id, floor),
    )
