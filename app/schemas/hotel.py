import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class HotelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    address: str | None = None


class HotelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    address: str | None = None
    auto_approve_tasks: bool | None = None


class HotelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    address: str | None
    auto_approve_tasks: bool
    created_at: datetime
    updated_at: datetime
