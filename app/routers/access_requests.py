import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import generate_temp_password, hash_password
from app.database import get_db
from app.email import send_welcome_email_best_effort
from app.dependencies import (
    require_admin,
    require_requester,
    require_same_hotel,
)
from app.models.access_request import AccessRequest
from app.models.enums import RequestKind, RequestResource, RequestStatus, UserRole
from app.models.room import Room
from app.models.user import User
from app.routers.rooms import (
    _ensure_room_number_available,
    _get_room_in_hotel_or_404,
)
from app.routers.users import _ensure_email_available, _get_user_in_hotel_or_404
from app.schemas.access_request import (
    AccessRequestCreate,
    AccessRequestDecision,
    AccessRequestRead,
    AccessRequestReject,
    RoomAddPayload,
    StaffAddPayload,
)

router = APIRouter(prefix="/api/v1", tags=["access-requests"])


async def _get_request_or_404(
    db: AsyncSession, request_id: uuid.UUID
) -> AccessRequest:
    req = await db.get(AccessRequest, request_id)
    if req is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Request not found"
        )
    return req


async def _ensure_no_open_remove(
    db: AsyncSession, resource: RequestResource, target_id: uuid.UUID
) -> None:
    """A given user/room may have at most one pending remove request open (also
    enforced by a partial unique index; this gives a friendly error first)."""
    result = await db.execute(
        select(AccessRequest.id).where(
            AccessRequest.resource == resource,
            AccessRequest.kind == RequestKind.REMOVE,
            AccessRequest.target_id == target_id,
            AccessRequest.status == RequestStatus.PENDING,
        )
    )
    if result.first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A pending removal request already exists for this item",
        )


async def _ensure_no_open_add(
    db: AsyncSession,
    hotel_id: uuid.UUID,
    resource: RequestResource,
    *,
    field: str,
    value: str,
) -> None:
    """At most one pending add request per staff email / room number in a hotel
    — the identity lives in the JSONB payload since no row exists yet. Also
    enforced by a partial unique index; this gives a friendly error first."""
    result = await db.execute(
        select(AccessRequest.id).where(
            AccessRequest.hotel_id == hotel_id,
            AccessRequest.resource == resource,
            AccessRequest.kind == RequestKind.ADD,
            AccessRequest.status == RequestStatus.PENDING,
            AccessRequest.payload[field].astext == value,
        )
    )
    if result.first() is not None:
        subject = (
            "staff email"
            if resource is RequestResource.STAFF
            else "room number"
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A pending add request already exists for this {subject}",
        )


# --------------------------------------------------------------------------- #
# Manager-facing (hotel-scoped)
# --------------------------------------------------------------------------- #


@router.post(
    "/hotels/{hotel_id}/access-requests",
    response_model=AccessRequestRead,
    status_code=status.HTTP_201_CREATED,
)
async def file_access_request(
    hotel_id: uuid.UUID,
    payload: AccessRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_requester),
) -> AccessRequest:
    """A manager asks a platform admin to add or remove a staff member or room.
    The request is only validated here; nothing is created/deleted until an
    admin approves it."""
    require_same_hotel(hotel_id, current_user)

    stored_payload: dict | None = None

    if payload.kind is RequestKind.ADD:
        if payload.resource is RequestResource.STAFF:
            assert isinstance(payload.payload, StaffAddPayload)
            await _ensure_email_available(db, payload.payload.email)
            await _ensure_no_open_add(
                db,
                hotel_id,
                RequestResource.STAFF,
                field="email",
                value=str(payload.payload.email),
            )
        else:  # ROOM
            assert isinstance(payload.payload, RoomAddPayload)
            await _ensure_room_number_available(
                db, hotel_id, payload.payload.room_number
            )
            await _ensure_no_open_add(
                db,
                hotel_id,
                RequestResource.ROOM,
                field="room_number",
                value=payload.payload.room_number,
            )
        stored_payload = payload.payload.model_dump(mode="json")
    else:  # REMOVE
        assert payload.target_id is not None
        if payload.resource is RequestResource.STAFF:
            target = await _get_user_in_hotel_or_404(
                db, hotel_id, payload.target_id
            )
            if target.id == current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="You cannot request removal of your own account",
                )
            if target.role is UserRole.ADMIN:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Admins cannot be removed through a staff request",
                )
        else:  # ROOM
            await _get_room_in_hotel_or_404(db, hotel_id, payload.target_id)
        await _ensure_no_open_remove(db, payload.resource, payload.target_id)

    req = AccessRequest(
        hotel_id=hotel_id,
        resource=payload.resource,
        kind=payload.kind,
        status=RequestStatus.PENDING,
        requested_by=current_user.id,
        target_id=payload.target_id,
        payload=stored_payload,
        note=payload.note,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)
    return req


@router.get(
    "/hotels/{hotel_id}/access-requests",
    response_model=list[AccessRequestRead],
)
async def list_hotel_access_requests(
    hotel_id: uuid.UUID,
    status_filter: RequestStatus | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_requester),
) -> list[AccessRequest]:
    """A manager sees their own hotel's requests (to track pending/decided)."""
    require_same_hotel(hotel_id, current_user)
    query = select(AccessRequest).where(AccessRequest.hotel_id == hotel_id)
    if status_filter is not None:
        query = query.where(AccessRequest.status == status_filter)
    query = query.order_by(AccessRequest.created_at.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


# --------------------------------------------------------------------------- #
# Admin-facing (platform, cross-tenant)
# --------------------------------------------------------------------------- #


@router.get("/access-requests", response_model=list[AccessRequestRead])
async def list_access_requests(
    status_filter: RequestStatus | None = Query(
        default=RequestStatus.PENDING, alias="status"
    ),
    hotel_id: uuid.UUID | None = None,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[AccessRequest]:
    """The global queue across all hotels. Defaults to pending."""
    query = select(AccessRequest)
    if status_filter is not None:
        query = query.where(AccessRequest.status == status_filter)
    if hotel_id is not None:
        query = query.where(AccessRequest.hotel_id == hotel_id)
    query = query.order_by(AccessRequest.created_at)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post(
    "/access-requests/{request_id}/approve",
    response_model=AccessRequestDecision,
)
async def approve_access_request(
    request_id: uuid.UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AccessRequestDecision:
    """Perform the requested add/remove and close the request in one
    transaction, so the record and the action can never diverge. Idempotent-
    guarded: acting on an already-decided request returns 409."""
    req = await _get_request_or_404(db, request_id)
    if req.status is not RequestStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Request is already {req.status.value}",
        )

    temp_password: str | None = None
    # Set when this approval creates a staff account, so we can welcome-email
    # them after the commit succeeds.
    new_staff: StaffAddPayload | None = None

    if req.kind is RequestKind.ADD:
        if req.resource is RequestResource.STAFF:
            data = StaffAddPayload(**(req.payload or {}))
            # The email may have been taken since the request was filed.
            await _ensure_email_available(db, data.email)
            temp_password = generate_temp_password()
            new_staff = data
            db.add(
                User(
                    hotel_id=req.hotel_id,
                    email=data.email,
                    password_hash=hash_password(temp_password),
                    name=data.name,
                    role=data.role,
                    must_change_password=True,
                )
            )
        else:  # ROOM
            data = RoomAddPayload(**(req.payload or {}))
            await _ensure_room_number_available(
                db, req.hotel_id, data.room_number
            )
            db.add(Room(hotel_id=req.hotel_id, **data.model_dump()))
    else:  # REMOVE
        assert req.target_id is not None
        if req.resource is RequestResource.STAFF:
            target_user = await db.get(User, req.target_id)
            # No-op if the user is already gone (still close the request); never
            # remove an admin through this path.
            if (
                target_user is not None
                and target_user.hotel_id == req.hotel_id
                and target_user.role is not UserRole.ADMIN
            ):
                await db.delete(target_user)
        else:  # ROOM
            target_room = await db.get(Room, req.target_id)
            if target_room is not None and target_room.hotel_id == req.hotel_id:
                await db.delete(target_room)

    req.status = RequestStatus.APPROVED
    req.decided_by = current_user.id
    req.decided_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(req)

    # Welcome the newly-created staff member with their temp password + sign-in
    # link. Best-effort: the account is committed, so a mail failure must not
    # fail the approval.
    if new_staff is not None and temp_password is not None:
        await send_welcome_email_best_effort(
            to=new_staff.email,
            name=new_staff.name,
            temp_password=temp_password,
        )

    return AccessRequestDecision(
        request=AccessRequestRead.model_validate(req),
        temporary_password=temp_password,
    )


@router.post(
    "/access-requests/{request_id}/reject",
    response_model=AccessRequestRead,
)
async def reject_access_request(
    request_id: uuid.UUID,
    payload: AccessRequestReject,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AccessRequest:
    req = await _get_request_or_404(db, request_id)
    if req.status is not RequestStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Request is already {req.status.value}",
        )
    req.status = RequestStatus.REJECTED
    req.decision_note = payload.decision_note
    req.decided_by = current_user.id
    req.decided_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(req)
    return req
