import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import generate_temp_password, hash_password
from app.database import get_db
from app.dependencies import (
    require_admin,
    require_manager_or_above,
    require_same_hotel,
)
from app.models.hotel import Hotel
from app.models.room import Room
from app.models.user import User
from app.schemas.hotel import (
    HotelCreate,
    HotelRead,
    HotelUpdate,
    TaskApprovalSetting,
)
from app.schemas.provision import (
    HotelProvisionRequest,
    HotelProvisionResponse,
)
from app.schemas.user import UserRead

router = APIRouter(prefix="/api/v1/hotels", tags=["hotels"])


async def _get_hotel_or_404(db: AsyncSession, hotel_id: uuid.UUID) -> Hotel:
    hotel = await db.get(Hotel, hotel_id)
    if hotel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Hotel not found"
        )
    return hotel


@router.get("", response_model=list[HotelRead])
async def list_hotels(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[Hotel]:
    """List all hotels. Platform-level action, admin only (owner console)."""
    result = await db.execute(select(Hotel).order_by(Hotel.name))
    return list(result.scalars().all())


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


@router.post(
    "/provision",
    response_model=HotelProvisionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def provision_hotel(
    payload: HotelProvisionRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> HotelProvisionResponse:
    """Create a hotel and optionally bulk-import its rooms and staff, atomically.

    All-or-nothing: if any row fails validation, nothing is committed — not even
    the hotel. All row errors are collected and returned together (422) so the
    caller can fix the whole file at once. Provisioned users share one temporary
    password (returned once) and must change it on first login.
    """
    errors: list[dict[str, object]] = []

    # Rooms: room_number is unique per hotel; catch in-batch duplicates.
    seen_rooms: dict[str, int] = {}
    for i, room in enumerate(payload.rooms):
        key = room.room_number
        if key in seen_rooms:
            errors.append(
                {
                    "sheet": "rooms",
                    "row": i,
                    "field": "room_number",
                    "message": f"Duplicate room number '{key}' "
                    f"(also in row {seen_rooms[key]})",
                }
            )
        else:
            seen_rooms[key] = i

    # Users: email is globally unique; catch in-batch duplicates (case-insensitive)
    # and any that already belong to an existing account.
    seen_emails: dict[str, int] = {}
    for i, user in enumerate(payload.users):
        key = user.email.lower()
        if key in seen_emails:
            errors.append(
                {
                    "sheet": "users",
                    "row": i,
                    "field": "email",
                    "message": f"Duplicate email '{user.email}' "
                    f"(also in row {seen_emails[key]})",
                }
            )
        else:
            seen_emails[key] = i

    if seen_emails:
        result = await db.execute(
            select(func.lower(User.email)).where(
                func.lower(User.email).in_(seen_emails.keys())
            )
        )
        taken = set(result.scalars().all())
        for key, i in seen_emails.items():
            if key in taken:
                errors.append(
                    {
                        "sheet": "users",
                        "row": i,
                        "field": "email",
                        "message": f"A user with email "
                        f"'{payload.users[i].email}' already exists",
                    }
                )

    if errors:
        errors.sort(key=lambda e: (str(e["sheet"]), int(e["row"])))  # type: ignore[arg-type]
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": f"{len(errors)} row(s) could not be imported. "
                "Nothing was created.",
                "errors": errors,
            },
        )

    # Single transaction: any failure below rolls the whole thing back.
    hotel = Hotel(**payload.hotel.model_dump())
    db.add(hotel)
    await db.flush()

    for room in payload.rooms:
        db.add(Room(hotel_id=hotel.id, **room.model_dump()))

    temp_password = generate_temp_password()
    temp_hash = hash_password(temp_password)
    created_users = [
        User(
            hotel_id=hotel.id,
            email=user.email,
            password_hash=temp_hash,
            name=user.name,
            role=user.role,
            must_change_password=True,
        )
        for user in payload.users
    ]
    db.add_all(created_users)

    await db.commit()

    await db.refresh(hotel)
    for user in created_users:
        await db.refresh(user)

    return HotelProvisionResponse(
        hotel=HotelRead.model_validate(hotel),
        rooms_created=len(payload.rooms),
        users=[UserRead.model_validate(u) for u in created_users],
        temporary_password=temp_password,
    )


@router.get("/{hotel_id}", response_model=HotelRead)
async def get_hotel(
    hotel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
) -> Hotel:
    """View a hotel's profile. Manager+ only — housekeepers have no feature that
    needs it. Managers are scoped to their own hotel; admins are cross-tenant."""
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


@router.patch("/{hotel_id}/task-approval", response_model=HotelRead)
async def set_task_approval(
    hotel_id: uuid.UUID,
    payload: TaskApprovalSetting,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
) -> Hotel:
    """Toggle whether completing a task auto-approves (skips the manager sign-off
    step). Hotel ops (manager/front-desk) own this, so it's not admin-gated like
    the rest of hotel settings."""
    require_same_hotel(hotel_id, current_user)
    hotel = await _get_hotel_or_404(db, hotel_id)
    hotel.auto_approve_tasks = payload.auto_approve_tasks
    await db.commit()
    await db.refresh(hotel)
    return hotel
