import uuid
from datetime import date

from pydantic import BaseModel


class RoomTypeAvg(BaseModel):
    """Average clean time for one room type over the window."""

    room_type: str
    clean_count: int
    avg_seconds: float | None  # null when clean_count == 0


class HousekeeperRoomTypeAvg(BaseModel):
    housekeeper_id: uuid.UUID
    name: str
    by_room_type: list[RoomTypeAvg]


class CleanTimesResponse(BaseModel):
    from_date: date
    to_date: date
    # Hotel-wide averages by room type (all housekeepers), and the same broken
    # down per housekeeper.
    hotel_by_room_type: list[RoomTypeAvg]
    by_housekeeper: list[HousekeeperRoomTypeAvg]


class HousekeeperEfficiency(BaseModel):
    housekeeper_id: uuid.UUID
    name: str
    shifts_worked: int  # shifts that had assigned work (efficiency denominator)
    shifts_all_done: int  # of those, how many finished everything
    efficiency_pct: float | None  # null when shifts_worked == 0


class EfficiencyResponse(BaseModel):
    from_date: date
    to_date: date
    by_housekeeper: list[HousekeeperEfficiency]


class HousekeeperLoad(BaseModel):
    housekeeper_id: uuid.UUID
    name: str
    open_tasks: int  # current open tasks assigned to them (live, not windowed)
    tasks_completed: int  # completed within the window
    clean_seconds_total: int
    shift_seconds_total: int
    utilization_pct: float | None  # clean ÷ shift; null when no shift time


class TaskLoadResponse(BaseModel):
    from_date: date
    to_date: date
    by_housekeeper: list[HousekeeperLoad]
    hotel_clean_seconds_total: int
    hotel_shift_seconds_total: int
    hotel_utilization_pct: float | None
