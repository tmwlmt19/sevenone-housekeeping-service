import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_password
from app.database import get_db
from app.dependencies import (
    require_admin,
    require_manager_or_above,
    require_same_hotel,
)
from app.models.user import User
from app.schemas.user import UserRead, UserUpdate

router = APIRouter(prefix="/api/v1/hotels/{hotel_id}/users", tags=["users"])

# Staff create/delete is not exposed here: platform admins no longer add or
# remove staff directly. Those actions happen only when an admin approves a
# manager's request — see app/routers/access_requests.py. Editing an existing
# user (below) and bulk provisioning (hotels.py) remain admin-direct.


async def _get_user_in_hotel_or_404(
    db: AsyncSession, hotel_id: uuid.UUID, user_id: uuid.UUID
) -> User:
    user = await db.get(User, user_id)
    if user is None or user.hotel_id != hotel_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return user


async def _ensure_email_available(
    db: AsyncSession, email: str, *, exclude_user_id: uuid.UUID | None = None
) -> None:
    result = await db.execute(select(User).where(User.email == email))
    existing = result.scalar_one_or_none()
    if existing is not None and existing.id != exclude_user_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )


@router.get("", response_model=list[UserRead])
async def list_users(
    hotel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
) -> list[User]:
    require_same_hotel(hotel_id, current_user)
    result = await db.execute(
        select(User).where(User.hotel_id == hotel_id).order_by(User.created_at)
    )
    return list(result.scalars().all())


@router.get("/{user_id}", response_model=UserRead)
async def get_user(
    hotel_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
) -> User:
    require_same_hotel(hotel_id, current_user)
    return await _get_user_in_hotel_or_404(db, hotel_id, user_id)


@router.put("/{user_id}", response_model=UserRead)
async def update_user(
    hotel_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> User:
    require_same_hotel(hotel_id, current_user)
    user = await _get_user_in_hotel_or_404(db, hotel_id, user_id)

    data = payload.model_dump(exclude_unset=True)
    # Nobody may change their own role (prevents self-demotion / lockout).
    if (
        user_id == current_user.id
        and data.get("role") is not None
        and data["role"] != user.role
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot change your own role",
        )
    if "email" in data:
        await _ensure_email_available(db, data["email"], exclude_user_id=user_id)
    if "password" in data:
        user.password_hash = hash_password(data.pop("password"))
    for field, value in data.items():
        setattr(user, field, value)

    await db.commit()
    await db.refresh(user)
    return user
