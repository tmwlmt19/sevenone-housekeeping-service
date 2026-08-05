"""Normalization layer for PMS payloads.

Each PMS vendor may push a slightly different JSON shape. To keep the import core
format-agnostic, an *adapter* maps a raw payload onto the canonical inputs the
core consumes: a flat list of room-number strings plus a list of housekeeper
names. The default adapter below handles our documented simple contract; adding a
vendor with a bespoke shape means writing one more function here — the endpoint
and the core don't change.
"""

from typing import Any

# Header/field aliases accepted for a room's number, mirroring the CSV importer.
_ROOM_ALIASES = ("room_number", "room", "number", "room_no")


def _normalize_key(key: str) -> str:
    return key.strip().lower().replace("-", "_").replace(" ", "_")


def _room_from_entry(entry: Any) -> str | None:
    """Pull a room number out of one `rooms` entry (a bare string or an object
    keyed by an accepted alias). Returns None if nothing usable is present."""
    if isinstance(entry, str):
        return entry.strip() or None
    if isinstance(entry, (int, float)) and not isinstance(entry, bool):
        return str(entry).strip() or None
    if isinstance(entry, dict):
        normalized = {_normalize_key(str(k)): v for k, v in entry.items()}
        for alias in _ROOM_ALIASES:
            value = normalized.get(alias)
            if isinstance(value, bool):
                continue
            if isinstance(value, (str, int, float)) and str(value).strip():
                return str(value).strip()
    return None


def normalize_default(
    rooms: list[Any], housekeepers: list[Any]
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    """Canonicalize the default PMS contract.

    Returns `(room_numbers, housekeeper_names, errors)`. `errors` flags entries
    that carried no usable value so the caller can fold them into a single 422
    alongside the core's own validation. Blank/empty entries are dropped
    silently; only structurally unusable rows are reported.
    """
    room_numbers: list[str] = []
    errors: list[dict[str, Any]] = []

    for i, entry in enumerate(rooms):
        room_number = _room_from_entry(entry)
        if room_number is not None:
            room_numbers.append(room_number)
        elif entry not in (None, "", {}):
            # Non-empty but we couldn't find a room number in it — surface it.
            errors.append(
                {
                    "field": "rooms",
                    "value": entry,
                    "message": f"Entry {i} has no recognizable room number",
                }
            )

    housekeeper_names = [
        h.strip() for h in housekeepers if isinstance(h, str) and h.strip()
    ]

    return room_numbers, housekeeper_names, errors
