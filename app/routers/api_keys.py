import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    API_KEY_DISPLAY_LEN,
    generate_api_key,
    hash_api_key,
)
from app.database import get_db
from app.dependencies import require_admin
from app.models.hotel import Hotel
from app.models.hotel_api_key import HotelApiKey
from app.models.user import User
from app.schemas.api_key import ApiKeyCreate, ApiKeyCreateResponse, ApiKeyRead

# Per-hotel PMS API keys. Managing them is a platform-admin action (the same
# people who provision hotels), so this lives under the admin-only hotels tree.
router = APIRouter(prefix="/api/v1/hotels/{hotel_id}/api-keys", tags=["api-keys"])


async def _get_hotel_or_404(db: AsyncSession, hotel_id: uuid.UUID) -> Hotel:
    hotel = await db.get(Hotel, hotel_id)
    if hotel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Hotel not found"
        )
    return hotel


@router.get("", response_model=list[ApiKeyRead])
async def list_api_keys(
    hotel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[HotelApiKey]:
    """List a hotel's API keys (metadata only — secrets are never returned)."""
    await _get_hotel_or_404(db, hotel_id)
    result = await db.execute(
        select(HotelApiKey)
        .where(HotelApiKey.hotel_id == hotel_id)
        .order_by(HotelApiKey.created_at.desc())
    )
    return list(result.scalars().all())


@router.post(
    "", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED
)
async def create_api_key(
    hotel_id: uuid.UUID,
    payload: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> ApiKeyCreateResponse:
    """Mint a new API key for a hotel. The full secret is returned exactly once;
    only its hash is stored, so it can never be shown again."""
    await _get_hotel_or_404(db, hotel_id)

    raw_key = generate_api_key()
    api_key = HotelApiKey(
        hotel_id=hotel_id,
        name=payload.name,
        key_prefix=raw_key[:API_KEY_DISPLAY_LEN],
        key_hash=hash_api_key(raw_key),
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    return ApiKeyCreateResponse(
        api_key=ApiKeyRead.model_validate(api_key), key=raw_key
    )


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    hotel_id: uuid.UUID,
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> None:
    """Revoke (disable) an API key. Idempotent — revoking an already-revoked key
    is a no-op. The row is kept so its prefix/last-used stay auditable."""
    api_key = await db.get(HotelApiKey, key_id)
    if api_key is None or api_key.hotel_id != hotel_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="API key not found"
        )
    if api_key.revoked_at is None:
        api_key.revoked_at = datetime.now(timezone.utc)
        await db.commit()
