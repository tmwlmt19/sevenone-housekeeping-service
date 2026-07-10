from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import UserRole
from app.schemas.hotel import HotelCreate, HotelRead
from app.schemas.room import RoomCreate
from app.schemas.user import UserRead

# Roles that may be created via provisioning/import. Admin is a platform-level
# role and is never created for a tenant this way.
_PROVISIONABLE_ROLES = {UserRole.MANAGER, UserRole.HOUSEKEEPER}


class UserProvision(BaseModel):
    """A staff row in a provisioning batch. No password: every provisioned user
    gets the batch's shared temporary password and must change it on first login."""

    email: EmailStr
    name: str = Field(min_length=1, max_length=255)
    role: UserRole

    @field_validator("role")
    @classmethod
    def _role_is_provisionable(cls, value: UserRole) -> UserRole:
        if value not in _PROVISIONABLE_ROLES:
            raise ValueError("Role must be manager or housekeeper")
        return value


class HotelProvisionRequest(BaseModel):
    """Create a hotel and (optionally) bulk-import its rooms and staff in one
    atomic operation. Both lists are optional; either or both may be empty."""

    hotel: HotelCreate
    rooms: list[RoomCreate] = Field(default_factory=list)
    users: list[UserProvision] = Field(default_factory=list)


class HotelProvisionResponse(BaseModel):
    hotel: HotelRead
    rooms_created: int
    users: list[UserRead]
    # The shared temporary password assigned to every provisioned user, returned
    # once so the admin can distribute it. Never stored in plaintext.
    temporary_password: str
