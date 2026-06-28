import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import (
    get_current_user,
    require_admin,
    require_same_hotel,
)
from app.models.hotel import Hotel
from app.models.user import User
from app.schemas.hotel import HotelCreate, HotelRead, HotelUpdate

router = APIRouter(prefix="/api/v1/hotels", tags=["hotels"])


async def _get_hotel_or_404(db: AsyncSession, hotel_id: uuid.UUID) -> Hotel:
    hotel = await db.get(Hotel, hotel_id)
    if hotel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Hotel not found"
        )
    return hotel


@router.post("", response_model=HotelRead, status_code=status.HTTP_201_CREATED)
async def create_hotel(
    payload: HotelCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> Hotel:
    """Create a new hotel (tenant). Platform-level action, admin only."""
    hotel = Hotel(**payload.model_dump())
    db.add(hotel)
    await db.commit()
    await db.refresh(hotel)
    return hotel


@router.get("/{hotel_id}", response_model=HotelRead)
async def get_hotel(
    hotel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Hotel:
    require_same_hotel(hotel_id, current_user)
    return await _get_hotel_or_404(db, hotel_id)


@router.put("/{hotel_id}", response_model=HotelRead)
async def update_hotel(
    hotel_id: uuid.UUID,
    payload: HotelUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Hotel:
    require_same_hotel(hotel_id, current_user)
    hotel = await _get_hotel_or_404(db, hotel_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(hotel, field, value)
    await db.commit()
    await db.refresh(hotel)
    return hotel
