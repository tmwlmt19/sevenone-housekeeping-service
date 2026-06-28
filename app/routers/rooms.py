import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import (
    get_current_user,
    require_manager_or_above,
    require_same_hotel,
)
from app.models.room import Room
from app.models.user import User
from app.schemas.room import RoomCreate, RoomRead, RoomUpdate

router = APIRouter(prefix="/api/v1/hotels/{hotel_id}/rooms", tags=["rooms"])


async def _get_room_in_hotel_or_404(
    db: AsyncSession, hotel_id: uuid.UUID, room_id: uuid.UUID
) -> Room:
    room = await db.get(Room, room_id)
    if room is None or room.hotel_id != hotel_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Room not found"
        )
    return room


async def _ensure_room_number_available(
    db: AsyncSession,
    hotel_id: uuid.UUID,
    room_number: str,
    *,
    exclude_room_id: uuid.UUID | None = None,
) -> None:
    result = await db.execute(
        select(Room).where(
            Room.hotel_id == hotel_id, Room.room_number == room_number
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None and existing.id != exclude_room_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A room with this number already exists in this hotel",
        )


@router.post("", response_model=RoomRead, status_code=status.HTTP_201_CREATED)
async def create_room(
    hotel_id: uuid.UUID,
    payload: RoomCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
) -> Room:
    require_same_hotel(hotel_id, current_user)
    await _ensure_room_number_available(db, hotel_id, payload.room_number)

    room = Room(hotel_id=hotel_id, **payload.model_dump())
    db.add(room)
    await db.commit()
    await db.refresh(room)
    return room


@router.get("", response_model=list[RoomRead])
async def list_rooms(
    hotel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Room]:
    require_same_hotel(hotel_id, current_user)
    result = await db.execute(
        select(Room)
        .where(Room.hotel_id == hotel_id)
        .order_by(Room.room_number)
    )
    return list(result.scalars().all())


@router.get("/{room_id}", response_model=RoomRead)
async def get_room(
    hotel_id: uuid.UUID,
    room_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Room:
    require_same_hotel(hotel_id, current_user)
    return await _get_room_in_hotel_or_404(db, hotel_id, room_id)


@router.put("/{room_id}", response_model=RoomRead)
async def update_room(
    hotel_id: uuid.UUID,
    room_id: uuid.UUID,
    payload: RoomUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
) -> Room:
    require_same_hotel(hotel_id, current_user)
    room = await _get_room_in_hotel_or_404(db, hotel_id, room_id)

    data = payload.model_dump(exclude_unset=True)
    if "room_number" in data:
        await _ensure_room_number_available(
            db, hotel_id, data["room_number"], exclude_room_id=room_id
        )
    for field, value in data.items():
        setattr(room, field, value)

    await db.commit()
    await db.refresh(room)
    return room


@router.delete("/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_room(
    hotel_id: uuid.UUID,
    room_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
) -> None:
    require_same_hotel(hotel_id, current_user)
    room = await _get_room_in_hotel_or_404(db, hotel_id, room_id)
    await db.delete(room)
    await db.commit()
