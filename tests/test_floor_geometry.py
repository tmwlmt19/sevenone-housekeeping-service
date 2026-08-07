"""Pure geometry helpers behind floor-map validation + the polygon migration."""

from app.services.floor_geometry import (
    bounding_box,
    is_simple_polygon,
    polygon_area,
    rect_to_vertices,
    round_polygon,
    within_coord_bounds,
)


def test_rect_to_vertices_axis_aligned():
    assert rect_to_vertices(10, 20, 13, 26) == [
        [10, 20], [23, 20], [23, 46], [10, 46]
    ]


def test_rect_to_vertices_right_angle_swaps_w_h_about_center():
    # A 90° rotation swaps width/height about the same center — visually identical
    # for a rectangle, so the migration is lossless.
    verts = rect_to_vertices(0, 0, 10, 20, rotation=90)
    min_x, min_y, max_x, max_y = bounding_box(verts)
    assert (max_x - min_x, max_y - min_y) == (20, 10)
    # Center is preserved at (5, 10).
    assert ((min_x + max_x) / 2, (min_y + max_y) / 2) == (5, 10)


def test_polygon_area_rectangle():
    assert polygon_area(rect_to_vertices(0, 0, 10, 4)) == 40.0


def test_polygon_area_triangle():
    assert polygon_area([[0, 0], [10, 0], [0, 10]]) == 50.0


def test_polygon_area_zero_for_collinear():
    assert polygon_area([[0, 0], [10, 0], [20, 0]]) == 0.0


def test_is_simple_polygon_accepts_convex_and_concave():
    assert is_simple_polygon(rect_to_vertices(0, 0, 10, 10)) is True
    # An L-shape (concave but simple).
    assert is_simple_polygon(
        [[0, 0], [20, 0], [20, 10], [10, 10], [10, 20], [0, 20]]
    ) is True
    # A house/pentagon (square + triangular roof).
    assert is_simple_polygon(
        [[0, 0], [10, 0], [10, 10], [5, 15], [0, 10]]
    ) is True


def test_is_simple_polygon_rejects_bowtie():
    assert is_simple_polygon([[0, 0], [10, 10], [10, 0], [0, 10]]) is False


def test_within_coord_bounds():
    assert within_coord_bounds([[0, 0], [10, 10]]) is True
    assert within_coord_bounds([[0, 0], [1e9, 0]]) is False
    assert within_coord_bounds([[float("nan"), 0]]) is False


def test_round_polygon_trims_float_noise():
    assert round_polygon([[1.005, 2.994], [3.0, 4.0]]) == [[1.0, 2.99], [3.0, 4.0]]
