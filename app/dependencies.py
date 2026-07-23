import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import decode_access_token, hash_api_key
from app.config import get_settings
from app.database import get_db
from app.models.enums import UserRole
from app.models.hotel import Hotel
from app.models.hotel_api_key import HotelApiKey
from app.models.user import User

settings = get_settings()

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)

_API_KEY_HEADER = "X-API-Key"
_API_KEY_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or missing API key",
)


def _token_from_request(request: Request) -> str | None:
    """Prefer the SSO session cookie; fall back to a bearer header (tests/tools)."""
    cookie = request.cookies.get(settings.session_cookie_name)
    if cookie:
        return cookie
    header = request.headers.get("Authorization")
    if header and header.lower().startswith("bearer "):
        return header[7:]
    return None


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    token = _token_from_request(request)
    if token is None:
        raise _CREDENTIALS_ERROR

    claims = decode_access_token(token)
    if claims is None:
        raise _CREDENTIALS_ERROR

    subject = claims.get("sub")
    if subject is None:
        raise _CREDENTIALS_ERROR
    try:
        user_id = uuid.UUID(subject)
    except (ValueError, TypeError):
        raise _CREDENTIALS_ERROR

    user = await db.get(User, user_id)
    if user is None:
        raise _CREDENTIALS_ERROR
    return user


async def get_hotel_from_api_key(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Hotel:
    """Authenticate a machine caller (e.g. a PMS) by its per-hotel API key.

    The hotel is derived entirely from the key — never from client input — so a
    key can only ever act on its own tenant. Returns the owning Hotel."""
    presented = request.headers.get(_API_KEY_HEADER)
    if not presented:
        raise _API_KEY_ERROR

    result = await db.execute(
        select(HotelApiKey).where(
            HotelApiKey.key_hash == hash_api_key(presented),
            HotelApiKey.revoked_at.is_(None),
        )
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise _API_KEY_ERROR

    api_key.last_used_at = datetime.now(timezone.utc)

    hotel = await db.get(Hotel, api_key.hotel_id)
    if hotel is None:
        raise _API_KEY_ERROR
    return hotel


def require_roles(*roles: UserRole) -> Callable[[User], Awaitable[User]]:
    """Dependency factory: allow only users whose role is in `roles`."""

    async def _checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return current_user

    return _checker


# Common role guards.
require_admin = require_roles(UserRole.ADMIN)
# Hotel-ops roles: manager and front desk share the same operational powers
# (room status, task CRUD, viewing staff/hotel). Admin is included as the
# platform superset.
require_manager_or_above = require_roles(
    UserRole.ADMIN, UserRole.MANAGER, UserRole.FRONT_DESK
)
# Filing/tracking staff & room access requests is the one hotel-ops power front
# desk does NOT have — only managers (and admins) may request add/remove.
require_requester = require_roles(UserRole.ADMIN, UserRole.MANAGER)


def require_same_hotel(hotel_id: uuid.UUID, current_user: User) -> None:
    """Enforce tenant isolation: a user may only act within their own hotel.

    Admins are platform-level (the owner console) and are NOT hotel-scoped —
    they may act across all hotels.
    """
    if current_user.role == UserRole.ADMIN:
        return
    if current_user.hotel_id != hotel_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resource not found",
        )
