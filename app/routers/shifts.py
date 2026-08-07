import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_same_hotel
from app.models.enums import ShiftCloseReason, UserRole
from app.models.user import User
from app.schemas.shift import CurrentShiftResponse, ShiftRead
from app.services import shifts

router = APIRouter(prefix="/api/v1/hotels/{hotel_id}/shifts", tags=["shifts"])


def _require_housekeeper(current_user: User) -> None:
    """Only housekeepers have shifts — clock-in/out is their flow."""
    if current_user.role != UserRole.HOUSEKEEPER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only housekeepers clock in and out of shifts",
        )


@router.get("/current", response_model=CurrentShiftResponse)
async def current_shift(
    hotel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CurrentShiftResponse:
    """The caller's own open shift (or null). Backs the clock-in gate."""
    require_same_hotel(hotel_id, current_user)
    _require_housekeeper(current_user)
    shift = await shifts.get_open_shift(
        db, hotel_id=hotel_id, housekeeper_id=current_user.id
    )
    return CurrentShiftResponse(shift=shift)


@router.post("/clock-in", response_model=ShiftRead, status_code=status.HTTP_201_CREATED)
async def clock_in(
    hotel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ShiftRead:
    """Open a shift for the caller (auto-closing any stale open one first)."""
    require_same_hotel(hotel_id, current_user)
    _require_housekeeper(current_user)
    shift = await shifts.clock_in(
        db, hotel_id=hotel_id, housekeeper_id=current_user.id
    )
    await db.commit()
    await db.refresh(shift)
    return shift


@router.post("/clock-out", response_model=CurrentShiftResponse)
async def clock_out(
    hotel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CurrentShiftResponse:
    """Close the caller's open shift. Idempotent — returns null if none open."""
    require_same_hotel(hotel_id, current_user)
    _require_housekeeper(current_user)
    shift = await shifts.get_open_shift(
        db, hotel_id=hotel_id, housekeeper_id=current_user.id
    )
    if shift is None:
        return CurrentShiftResponse(shift=None)
    await shifts.close_shift(db, shift, reason=ShiftCloseReason.LOGOUT)
    await db.commit()
    await db.refresh(shift)
    return CurrentShiftResponse(shift=shift)
