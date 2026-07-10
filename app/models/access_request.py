import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    RequestKind,
    RequestResource,
    RequestStatus,
    pg_enum,
)

if TYPE_CHECKING:
    from app.models.hotel import Hotel
    from app.models.user import User


class AccessRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A manager's request for a platform admin to add or remove a staff member
    or a room. Admins no longer create/delete these resources directly — an
    approved request is the only path, and approval performs the action in the
    same transaction that records the decision, so the two can't diverge."""

    __tablename__ = "access_requests"
    __mapper_args__ = {"eager_defaults": True}

    hotel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hotels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resource: Mapped[RequestResource] = mapped_column(
        pg_enum(RequestResource, "request_resource"), nullable=False
    )
    kind: Mapped[RequestKind] = mapped_column(
        pg_enum(RequestKind, "request_kind"), nullable=False
    )
    status: Mapped[RequestStatus] = mapped_column(
        pg_enum(RequestStatus, "request_status"),
        nullable=False,
        default=RequestStatus.PENDING,
        index=True,
    )

    # The manager who filed it. Kept (SET NULL) if that user is later removed so
    # the audit trail survives.
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # For remove requests: the id of the user or room to remove. Not a hard FK
    # because it points at different tables depending on `resource`.
    target_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # For add requests: the proposed resource. Staff: {name, email, role}.
    # Room: {room_number, floor, room_type, status}. No password — the temp
    # password is generated at approval time and shown once to the admin.
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    hotel: Mapped["Hotel"] = relationship()
    requester: Mapped["User | None"] = relationship(foreign_keys=[requested_by])
    decider: Mapped["User | None"] = relationship(foreign_keys=[decided_by])
