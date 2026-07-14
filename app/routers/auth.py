import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token, hash_password, verify_password
from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_user
from app.email import send_password_reset_email
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    PasswordChange,
    ResetPasswordRequest,
    Token,
)
from app.schemas.user import PreferencesUpdate, UserRead

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

logger = logging.getLogger(__name__)
settings = get_settings()

# Shown for every forgot-password call so the response never reveals whether an
# account exists (no account enumeration).
_FORGOT_PASSWORD_MESSAGE = "If that email exists, a reset link has been sent."


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        path="/",
    )


@router.post("/login", response_model=Token)
async def login(
    credentials: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> Token:
    result = await db.execute(
        select(User).where(User.email == credentials.email)
    )
    user = result.scalar_one_or_none()

    if user is None or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(
        subject=str(user.id),
        extra_claims={
            # Service admins have no hotel; keep the claim null rather than "None".
            "hotel_id": str(user.hotel_id) if user.hotel_id else None,
            "role": user.role.value,
        },
    )
    # Set the SSO session cookie (shared across the login/hotel/admin apps) and
    # also return the token for API clients / tests using bearer auth.
    _set_session_cookie(response, token)
    return Token(access_token=token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        domain=settings.cookie_domain,
        path="/",
    )


@router.post("/forgot-password")
async def forgot_password(
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Start a self-service password reset.

    Always returns the same generic 200 whether or not the email matches a
    user, so the endpoint never reveals which addresses have accounts.
    """
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if user is not None:
        now = datetime.now(timezone.utc)
        throttle_cutoff = now - timedelta(
            seconds=settings.password_reset_min_interval_seconds
        )
        recent = await db.execute(
            select(PasswordResetToken.id)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.created_at > throttle_cutoff,
            )
            .limit(1)
        )
        # Skip minting if the user already got a token very recently.
        if recent.scalar_one_or_none() is None:
            raw_token = secrets.token_urlsafe(32)
            expires_at = now + timedelta(
                minutes=settings.password_reset_token_ttl_minutes
            )
            # Keep at most one live token: retire the user's prior unused ones.
            await db.execute(
                update(PasswordResetToken)
                .where(
                    PasswordResetToken.user_id == user.id,
                    PasswordResetToken.used_at.is_(None),
                )
                .values(used_at=now)
            )
            db.add(
                PasswordResetToken(
                    user_id=user.id,
                    token_hash=_hash_token(raw_token),
                    expires_at=expires_at,
                )
            )
            await db.commit()

            reset_url = f"{settings.password_reset_url_base}?token={raw_token}"
            try:
                await send_password_reset_email(
                    to=user.email, reset_url=reset_url
                )
            except Exception:
                # Never surface send failures to the client (would leak
                # existence); log for operators instead.
                logger.exception("Failed to send password reset email")

    return {"message": _FORGOT_PASSWORD_MESSAGE}


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Consume a reset token and set a new password."""
    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == _hash_token(payload.token)
        )
    )
    token = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if token is None or token.used_at is not None or token.expires_at <= now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset link.",
        )

    user = await db.get(User, token.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset link.",
        )

    user.password_hash = hash_password(payload.new_password)
    # The user has now chosen their own password; clear any forced-change flag.
    user.must_change_password = False
    token.used_at = now
    await db.commit()


@router.get("/me", response_model=UserRead)
async def read_current_user(
    current_user: User = Depends(get_current_user),
) -> User:
    return current_user


@router.patch("/me/preferences", response_model=UserRead)
async def update_my_preferences(
    payload: PreferencesUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """Update the authenticated user's own UI preferences (theme, language)."""
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(current_user, field, value)
    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.put("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_my_password(
    payload: PasswordChange,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Let the authenticated user change their own password."""
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    current_user.password_hash = hash_password(payload.new_password)
    # The user has now chosen their own password; clear any forced-change flag.
    current_user.must_change_password = False
    await db.commit()
