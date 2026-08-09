# SPDX-License-Identifier: MIT
"""Tests for Blender export coplanar region extraction."""

import pytest

from skppy.coplanar import PolygonBoundary, merge_coplanar_polygons


def _polygon(index, vertices, edges, *, material=0, z=0.0):
    return PolygonBoundary(index, tuple(vertices), tuple(edges), (0.0, 0.0, 1.0), -z, material)


def test_merges_adjacent_polygons_and_removes_shared_edge():
    positions = {0: (0, 0, 0), 1: (1, 0, 0), 2: (1, 1, 0), 3: (0, 1, 0)}
    polygons = [_polygon(0, (0, 1, 2), (0, 1, 4)), _polygon(1, (0, 2, 3), (4, 2, 3))]

    regions = merge_coplanar_polygons(polygons, positions)

    assert [region.polygons for region in regions] == [(0, 1)]
    assert [[edge.edge_index for edge in loop] for loop in regions[0].loops] == [[0, 1, 2, 3]]


def test_preserves_inner_boundary_as_hole():
    positions = {
        0: (0, 0, 0),
        1: (3, 0, 0),
        2: (3, 3, 0),
        3: (0, 3, 0),
        4: (1, 1, 0),
        5: (2, 1, 0),
        6: (2, 2, 0),
        7: (1, 2, 0),
    }
    polygons = [
        _polygon(0, (0, 1, 5, 4), (0, 1, 8, 9)),
        _polygon(1, (1, 2, 6, 5), (2, 3, 10, 1)),
        _polygon(2, (2, 3, 7, 6), (4, 5, 11, 3)),
        _polygon(3, (3, 0, 4, 7), (6, 9, 12, 5)),
    ]

    region = merge_coplanar_polygons(polygons, positions)[0]

    assert region.polygons == (0, 1, 2, 3)
    assert [[edge.edge_index for edge in loop] for loop in region.loops] == [[0, 2, 4, 6], [8, 12, 11, 10]]


def test_keeps_different_materials_and_planes_separate():
    positions = {0: (0, 0, 0), 1: (1, 0, 0), 2: (1, 1, 0), 3: (0, 1, 0)}
    polygons = [
        _polygon(0, (0, 1, 2), (0, 1, 4)),
        _polygon(1, (0, 2, 3), (4, 2, 3), material=1),
    ]

    regions = merge_coplanar_polygons(polygons, positions)

    assert [region.polygons for region in regions] == [(0,), (1,)]


def test_keeps_different_texture_projections_separate():
    positions = {0: (0, 0, 0), 1: (1, 0, 0), 2: (1, 1, 0), 3: (0, 1, 0)}
    polygons = [
        PolygonBoundary(0, (0, 1, 2), (0, 1, 4), (0, 0, 1), 0, 0, (1, 0, 0)),
        PolygonBoundary(1, (0, 2, 3), (4, 2, 3), (0, 0, 1), 0, 0, (2, 0, 0)),
    ]

    regions = merge_coplanar_polygons(polygons, positions)

    assert [region.polygons for region in regions] == [(0,), (1,)]


def test_rejects_open_non_manifold_region_boundary():
    positions = {0: (0, 0, 0), 1: (1, 0, 0), 2: (0, 1, 0), 3: (1, 1, 0)}
    polygons = [_polygon(0, (0, 1, 2), (0, 1, 2)), _polygon(1, (0, 1, 3), (0, 3, 4))]

    with pytest.raises(ValueError, match="open or non-manifold"):
        merge_coplanar_polygons(polygons, positions)
