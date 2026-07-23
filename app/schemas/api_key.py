import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyCreate(BaseModel):
    """Request to mint a new PMS API key for a hotel."""

    name: str = Field(min_length=1, max_length=255)


class ApiKeyRead(BaseModel):
    """A key's metadata. Never includes the secret — only the display prefix."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hotel_id: uuid.UUID
    name: str
    key_prefix: str
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ApiKeyCreateResponse(BaseModel):
    """Returned once at creation. `key` is the full secret and is never shown or
    stored again — the admin must copy it now."""

    api_key: ApiKeyRead
    key: str
