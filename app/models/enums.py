import enum

from sqlalchemy import Enum as SAEnum


def pg_enum(enum_cls: type[enum.Enum], name: str) -> SAEnum:
    """Build a native Postgres enum that persists the member *values*
    (e.g. 'admin') rather than the member *names* (e.g. 'ADMIN')."""
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda cls: [member.value for member in cls],
    )


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    # Front desk: same hotel-ops capabilities as a manager, but cannot file
    # staff/room add-remove requests.
    FRONT_DESK = "front_desk"
    HOUSEKEEPER = "housekeeper"


class RoomStatus(str, enum.Enum):
    CLEAN = "clean"
    DIRTY = "dirty"
    IN_PROGRESS = "in_progress"
    OUT_OF_SERVICE = "out_of_service"


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    # Housekeeper finished; awaiting manager/front-desk sign-off (unless the
    # hotel auto-approves).
    PENDING_APPROVAL = "pending_approval"
    COMPLETED = "completed"


class TaskPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    URGENT = "urgent"


class RequestResource(str, enum.Enum):
    """What an access request operates on."""

    STAFF = "staff"
    ROOM = "room"


class RequestKind(str, enum.Enum):
    ADD = "add"
    REMOVE = "remove"


class RequestStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
