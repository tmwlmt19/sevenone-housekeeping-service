import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import UserRole

# Allowed UI-preference values. Kept here (not a DB enum) so adding a language
# or theme is a one-line change with no migration.
Theme = Literal["light", "dark", "system"]
Language = Literal["en", "es"]


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    role: UserRole


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    role: UserRole | None = None


class PreferencesUpdate(BaseModel):
    """Partial update of the current user's UI preferences."""

    theme: Theme | None = None
    preferred_language: Language | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hotel_id: uuid.UUID | None
    email: EmailStr
    name: str
    role: UserRole
    must_change_password: bool
    theme: Theme
    preferred_language: Language
    created_at: datetime
    updated_at: datetime
