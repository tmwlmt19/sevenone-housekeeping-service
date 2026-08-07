"""Pure polygon geometry for floor-map layout — the Python mirror of the web
app's `features/floor-map/geometry.ts`. Dependency-free and side-effect-free so
schema validation, the polygon-geometry migration, and tests can all reuse it.

A polygon is an ordered list of ``[x, y]`` float-foot vertices, *not* explicitly
closed (the edge from the last vertex back to the first closes it); a filled
polygon needs at least 3 vertices. Coordinates are rounded to ``COORD_PRECISION``
decimal places (0.01 ft) so float noise never leaks into storage.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

COORD_PRECISION = 2  # decimal places → 0.01 ft
MIN_POLYGON_AREA = 0.5  # sq ft; rejects degenerate / zero-area shapes
MAX_COORD = 10_000.0  # ft; sanity ceiling so garbage input can't reach storage

Point = list[float]
Polygon = list[Point]


def round_pt(p: Sequence[float]) -> Point:
    return [round(float(p[0]), COORD_PRECISION), round(float(p[1]), COORD_PRECISION)]


def round_polygon(pts: Sequence[Sequence[float]]) -> Polygon:
    return [round_pt(p) for p in pts]


def rect_to_vertices(
    x: float, y: float, w: float, h: float, rotation: int = 0
) -> Polygon:
    """The four corners of an axis-aligned ``w × h`` rect at ``(x, y)``.

    A right-angle ``rotation`` (0/90/180/270) is folded into the footprint by
    swapping ``w``/``h`` about the rect's center — visually identical for a
    rectangle and lossless without trig. This is exactly the conversion the
    polygon-geometry migration applies to the old ``{x, y, w, h, rotation}`` rows.
    """
    if rotation % 180 == 90:
        eff_w, eff_h = h, w
    else:
        eff_w, eff_h = w, h
    cx, cy = x + w / 2, y + h / 2
    nx, ny = cx - eff_w / 2, cy - eff_h / 2
    return round_polygon(
        [[nx, ny], [nx + eff_w, ny], [nx + eff_w, ny + eff_h], [nx, ny + eff_h]]
    )


def polygon_area(pts: Sequence[Sequence[float]]) -> float:
    """Unsigned polygon area via the shoelace formula (0 for < 3 vertices)."""
    n = len(pts)
    if n < 3:
        return 0.0
    total = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def bounding_box(pts: Sequence[Sequence[float]]) -> tuple[float, float, float, float]:
    """(min_x, min_y, max_x, max_y) — used by the migration downgrade to collapse
    a polygon back to an axis-aligned rect."""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def within_coord_bounds(pts: Sequence[Sequence[float]]) -> bool:
    """Every coordinate is finite and within the sanity ceiling."""
    return all(
        math.isfinite(p[0])
        and math.isfinite(p[1])
        and abs(p[0]) <= MAX_COORD
        and abs(p[1]) <= MAX_COORD
        for p in pts
    )


def _orientation(p: Sequence[float], q: Sequence[float], r: Sequence[float]) -> int:
    """Sign of the cross product (p→q) × (p→r): +1 ccw, -1 cw, 0 collinear."""
    val = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    if abs(val) < 1e-9:
        return 0
    return 1 if val > 0 else -1


def _segments_cross(a, b, c, d) -> bool:
    """True if segments ab and cd *properly* cross (not merely touch at an
    endpoint) — so shapes that share a vertex aren't flagged as self-intersecting."""
    o1 = _orientation(a, b, c)
    o2 = _orientation(a, b, d)
    o3 = _orientation(c, d, a)
    o4 = _orientation(c, d, b)
    return o1 != o2 and o3 != o4 and 0 not in (o1, o2, o3, o4)


def is_simple_polygon(pts: Sequence[Sequence[float]]) -> bool:
    """True when no two non-adjacent edges cross. Concave shapes (an L, a
    pentagon) are simple; a bowtie is not."""
    n = len(pts)
    if n < 3:
        return False
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        for j in range(i + 1, n):
            # Skip edges that share a vertex (adjacent, or the wrap-around pair).
            if (i + 1) % n == j or (j + 1) % n == i:
                continue
            c, d = pts[j], pts[(j + 1) % n]
            if _segments_cross(a, b, c, d):
                return False
    return True
