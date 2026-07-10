import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import UserRole, pg_enum

if TYPE_CHECKING:
    from app.models.hotel import Hotel
    from app.models.task import Task


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __mapper_args__ = {"eager_defaults": True}

    # Nullable: platform/service admins are cross-tenant and belong to no hotel.
    # Hotel staff (manager/housekeeper) always have one.
    hotel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hotels.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        pg_enum(UserRole, "user_role"), nullable=False
    )
    # Set when an account is provisioned with a shared/temporary password; the
    # login app forces the user to set their own password before proceeding.
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
    # UI preferences, persisted per-user so they follow the person across
    # devices. `theme` is one of light/dark/system; `preferred_language` is an
    # ISO-639-1 code (currently 'en' or 'es'). Values are validated at the API
    # edge (see app/schemas/user.py); stored as plain strings for easy
    # extensibility (new languages/themes need no migration).
    theme: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="system", default="system"
    )
    preferred_language: Mapped[str] = mapped_column(
        String(5), nullable=False, server_default="en", default="en"
    )

    hotel: Mapped["Hotel"] = relationship(back_populates="users")
    assigned_tasks: Mapped[list["Task"]] = relationship(
        back_populates="assignee", foreign_keys="Task.assigned_to"
    )
