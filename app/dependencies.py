import uuid
from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import decode_access_token
from app.database import get_db
from app.models.enums import UserRole
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login")

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
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
require_manager_or_above = require_roles(UserRole.ADMIN, UserRole.MANAGER)


def require_same_hotel(hotel_id: uuid.UUID, current_user: User) -> None:
    """Enforce tenant isolation: the user may only act within their own hotel.

    Admins are also scoped to their hotel in the MVP (single-hotel admins);
    cross-hotel platform administration is out of scope for now.
    """
    if current_user.hotel_id != hotel_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resource not found",
        )
