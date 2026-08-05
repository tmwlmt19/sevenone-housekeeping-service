from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_hotel_from_api_key
from app.models.hotel import Hotel
from app.schemas.task_import import (
    DirtyRoomImportResponse,
    PmsDirtyRoomsRequest,
)
from app.services.pms_adapters import normalize_default
from app.services.task_import import import_dirty_rooms

router = APIRouter(prefix="/api/v1/integrations/pms", tags=["integrations"])


@router.post(
    "/dirty-rooms",
    response_model=DirtyRoomImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def pms_dirty_rooms(
    payload: PmsDirtyRoomsRequest,
    db: AsyncSession = Depends(get_db),
    hotel: Hotel = Depends(get_hotel_from_api_key),
) -> DirtyRoomImportResponse:
    """Machine-to-machine entry point for a PMS to push rooms that need cleaning.

    Auth is a per-hotel API key (``X-API-Key`` header); the hotel is derived from
    the key, never from the request body. The payload is normalized by the default
    adapter, then handed to the shared import core (set rooms dirty, create tasks,
    optionally balance-assign to the named housekeepers). All-or-nothing: any
    unknown room or unmatched housekeeper fails the whole batch."""
    room_numbers, housekeeper_names, format_errors = normalize_default(
        payload.rooms, payload.housekeepers
    )
    summary = await import_dirty_rooms(
        db,
        hotel_id=hotel.id,
        room_numbers=room_numbers,
        housekeeper_refs=housekeeper_names,
        resolve_mode="name",
        priority=payload.priority,
        seed_errors=format_errors,
    )
    return DirtyRoomImportResponse(**summary)
