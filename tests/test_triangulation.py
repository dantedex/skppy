# SPDX-License-Identifier: MIT
import math

import pytest

from skppy.triangulation import split_single_hole_face_3d, triangulate_face_3d


def _triangle_quality(points, triangle):
    a, b, c = [points[i] for i in triangle]
    ax, ay, _az = a
    bx, by, _bz = b
    cx, cy, _cz = c
    ab2 = (bx - ax) * (bx - ax) + (by - ay) * (by - ay)
    bc2 = (cx - bx) * (cx - bx) + (cy - by) * (cy - by)
    ca2 = (ax - cx) * (ax - cx) + (ay - cy) * (ay - cy)
    area2 = abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax))
    return (2.0 * math.sqrt(3.0) * area2) / (ab2 + bc2 + ca2)


def _triangle_signed_area(points, triangle):
    """Return signed XY area for one indexed triangle."""
    a, b, c = [points[i] for i in triangle]
    return 0.5 * ((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))


def _strictly_intersects(first, second, points):
    """Return whether two edges without shared endpoints cross internally."""
    if set(first) & set(second):
        return False
    a, b = (points[index] for index in first)
    c, d = (points[index] for index in second)

    def side(origin, end, point):
        return (end[0] - origin[0]) * (point[1] - origin[1]) - (end[1] - origin[1]) * (point[0] - origin[0])

    return side(a, b, c) * side(a, b, d) < 0.0 and side(c, d, a) * side(c, d, b) < 0.0


def test_triangulates_concave_ngon_with_less_skinny_ears():
    polygon = [
        (0.0, 0.0, 0.0),
        (8.0, 0.0, 0.0),
        (8.0, 1.0, 0.0),
        (4.0, 1.0, 0.0),
        (4.0, 4.0, 0.0),
        (0.0, 4.0, 0.0),
    ]

    triangles = triangulate_face_3d(polygon, normal=(0.0, 0.0, 1.0))

    assert len(triangles) == len(polygon) - 2
    assert min(_triangle_quality(polygon, tri) for tri in triangles) > 0.25


def test_splits_single_hole_face_into_two_simple_ngons():
    outer = [
        (0.0, 0.0, 0.0),
        (4.0, 0.0, 0.0),
        (4.0, 4.0, 0.0),
        (0.0, 4.0, 0.0),
    ]
    hole = [
        (1.0, 1.0, 0.0),
        (1.0, 3.0, 0.0),
        (3.0, 3.0, 0.0),
        (3.0, 1.0, 0.0),
    ]

    polygons = split_single_hole_face_3d(outer, hole, normal=(0.0, 0.0, 1.0))

    assert len(polygons) == 2
    assert [len(poly) for poly in polygons] == [6, 6]
    assert all(len(set(poly)) == len(poly) for poly in polygons)


def test_multiple_hole_triangulation_preserves_topology_and_area():
    """Check the invariants importers depend on, not one triangle ordering."""
    outer = [
        (0.0, 0.0, 0.0),
        (10.0, 0.0, 0.0),
        (10.0, 8.0, 0.0),
        (0.0, 8.0, 0.0),
    ]
    holes = [
        [
            (2.0, 2.0, 0.0),
            (2.0, 4.0, 0.0),
            (4.0, 4.0, 0.0),
            (4.0, 2.0, 0.0),
        ],
        [
            (6.0, 3.0, 0.0),
            (6.0, 6.0, 0.0),
            (8.0, 6.0, 0.0),
            (8.0, 3.0, 0.0),
        ],
    ]
    points = outer + [point for hole in holes for point in hole]

    triangles = triangulate_face_3d(outer, holes, normal=(0.0, 0.0, 1.0))

    assert triangles
    assert all(len(set(triangle)) == 3 for triangle in triangles)
    assert all(0 <= index < len(points) for triangle in triangles for index in triangle)
    signed_areas = [_triangle_signed_area(points, triangle) for triangle in triangles]
    assert all(math.isfinite(area) and area > 0.0 for area in signed_areas)
    assert sum(signed_areas) == pytest.approx(70.0)

    edges = {
        tuple(sorted((triangle[index], triangle[(index + 1) % 3]))) for triangle in triangles for index in range(3)
    }
    assert not any(
        _strictly_intersects(first, second, points)
        for edge_index, first in enumerate(edges)
        for second in list(edges)[edge_index + 1 :]
    )

    for triangle in triangles:
        centroid = tuple(sum(points[index][axis] for index in triangle) / 3.0 for axis in range(2))
        assert not (2.0 < centroid[0] < 4.0 and 2.0 < centroid[1] < 4.0)
        assert not (6.0 < centroid[0] < 8.0 and 3.0 < centroid[1] < 6.0)


@pytest.mark.parametrize("scale", [1e-3, 1.0, 1e3])
def test_hole_triangulation_is_stable_across_model_scales(scale):
    """Keep topology and relative area stable for practical inch scales."""
    outer = [
        (0.0, 0.0, 0.0),
        (4.0 * scale, 0.0, 0.0),
        (4.0 * scale, 4.0 * scale, 0.0),
        (0.0, 4.0 * scale, 0.0),
    ]
    hole = [
        (1.0 * scale, 1.0 * scale, 0.0),
        (1.0 * scale, 3.0 * scale, 0.0),
        (3.0 * scale, 3.0 * scale, 0.0),
        (3.0 * scale, 1.0 * scale, 0.0),
    ]
    points = outer + hole

    triangles = triangulate_face_3d(outer, [hole], normal=(0.0, 0.0, 1.0))

    areas = [_triangle_signed_area(points, triangle) for triangle in triangles]
    assert triangles
    assert all(math.isfinite(area) and area > 0.0 for area in areas)
    assert sum(areas) == pytest.approx(12.0 * scale * scale)
