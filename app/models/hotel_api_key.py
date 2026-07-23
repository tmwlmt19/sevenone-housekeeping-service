import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.hotel import Hotel


class HotelApiKey(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A per-hotel API key that lets an external PMS push dirty-room data.

    We store only the SHA-256 hash of the key (see `app.auth.hash_api_key`); the
    raw value is shown to the admin once at creation and never persisted, so a DB
    leak can't be replayed. `key_prefix` keeps a few leading characters purely so
    the admin UI can tell keys apart. A non-null `revoked_at` disables the key.
    """

    __tablename__ = "hotel_api_keys"
    __mapper_args__ = {"eager_defaults": True}

    hotel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hotels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Human label so a hotel can name/rotate several keys (e.g. "Opera PMS").
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # First few characters of the key, for display only (never the secret).
    key_prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    key_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    hotel: Mapped["Hotel"] = relationship(back_populates="api_keys")
