# SPDX-License-Identifier: MIT
"""Degenerate and defensive boundary cases for polygon triangulation."""

from __future__ import annotations

from collections import Counter

import pytest

import skppy.triangulation as triangulation


SQUARE_3D = [
    (0.0, 0.0, 0.0),
    (4.0, 0.0, 0.0),
    (4.0, 4.0, 0.0),
    (0.0, 4.0, 0.0),
]
HOLE_3D = [
    (1.0, 1.0, 0.0),
    (1.0, 3.0, 0.0),
    (3.0, 3.0, 0.0),
    (3.0, 1.0, 0.0),
]


def test_public_triangulation_helpers_reject_incomplete_inputs():
    assert triangulation.triangulate_face_3d(SQUARE_3D[:2]) == []
    assert triangulation.split_single_hole_face_3d(SQUARE_3D[:2], HOLE_3D) == []
    assert triangulation.split_single_hole_face_3d(SQUARE_3D, HOLE_3D[:2]) == []
    assert triangulation.merge_triangles_to_ngons([], SQUARE_3D) == []


def test_split_single_hole_rejects_missing_bridge_pair(monkeypatch):
    monkeypatch.setattr(triangulation, "_find_split_bridge_pair", lambda *_args: None)
    assert triangulation.split_single_hole_face_3d(SQUARE_3D, HOLE_3D) == []


def test_split_single_hole_rejects_collapsed_polygon(monkeypatch):
    monkeypatch.setattr(triangulation, "_find_split_bridge_pair", lambda *_args: (0, 0, 0, 0))
    assert triangulation.split_single_hole_face_3d(SQUARE_3D, HOLE_3D) == []


def test_split_single_hole_rejects_zero_area_polygon(monkeypatch):
    monkeypatch.setattr(triangulation, "_find_split_bridge_pair", lambda *_args: (0, 0, 2, 2))
    areas = iter((1.0, 0.0))
    monkeypatch.setattr(triangulation, "_signed_polygon_area2", lambda _points: next(areas))
    assert triangulation.split_single_hole_face_3d(SQUARE_3D, HOLE_3D) == []


def test_split_single_hole_normalizes_polygon_winding(monkeypatch):
    monkeypatch.setattr(triangulation, "_find_split_bridge_pair", lambda *_args: (0, 0, 2, 2))
    areas = iter((1.0, -2.0, 2.0))
    monkeypatch.setattr(triangulation, "_signed_polygon_area2", lambda _points: next(areas))

    polygons = triangulation.split_single_hole_face_3d(SQUARE_3D, HOLE_3D)

    assert len(polygons) == 2
    assert polygons[0][0] == 4


def test_triangle_group_helpers_retain_invalid_groups(monkeypatch):
    triangles = [(0, 1, 2)]
    points = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]
    monkeypatch.setattr(triangulation, "_boundary_loop_for_triangle_group", lambda *_args: None)

    assert triangulation._triangle_group_adjacency({0: {0}}, triangles, points) == set()
    assert triangulation._triangle_group_loops({0: {0}}, triangles, points) == [[0, 1, 2]]


def test_boundary_helpers_reject_incomplete_disconnected_and_flat_boundaries():
    assert triangulation._boundary_adjacency([(0, 1), (1, 2)]) is None
    assert triangulation._trace_boundary_loop({0: [1, 1], 1: [0, 0]}, 0) is None

    flat = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]
    assert triangulation._boundary_loop_for_triangle_group({0}, [(0, 1, 2)], flat) is None


def test_simple_boundary_rejects_short_and_self_intersecting_loops():
    assert not triangulation._is_simple_boundary_loop([0, 1], [(0.0, 0.0)] * 2)
    bow_tie = [(0.0, 0.0), (2.0, 2.0), (0.0, 2.0), (2.0, 0.0)]
    assert not triangulation._is_simple_boundary_loop([0, 1, 2, 3], bow_tie)


@pytest.mark.parametrize(
    "normal",
    [(0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0)],
)
def test_projection_supports_degenerate_normal_and_each_reference_axis(normal):
    projected = triangulation._project_to_2d([(1.0, 2.0, 3.0)], normal)
    assert len(projected) == 1
    assert all(isinstance(value, float) for value in projected[0])


def test_bridge_visibility_rejects_midpoint_outside_outer_loop(monkeypatch):
    monkeypatch.setattr(triangulation, "_point_in_polygon", lambda *_args: False)
    assert not triangulation._bridge_visible_between_loops(0, 1, [[0, 1, 2]], [(0.0, 0.0), (1.0, 1.0), (0.0, 1.0)])


def test_bridge_visibility_rejects_crossing_and_touching_edges(monkeypatch):
    loops = [[0, 1, 2], [3, 4, 5]]
    points = [
        (0.0, 0.0),
        (4.0, 0.0),
        (0.0, 4.0),
        (1.0, 1.0),
        (2.0, 1.0),
        (1.0, 2.0),
    ]
    containment = iter((True, False))
    monkeypatch.setattr(triangulation, "_point_in_polygon", lambda *_args: next(containment))
    monkeypatch.setattr(triangulation, "_segments_intersect", lambda *_args: True)
    assert not triangulation._bridge_visible_between_loops(0, 3, loops, points)

    containment = iter((True, False))
    monkeypatch.setattr(triangulation, "_point_in_polygon", lambda *_args: next(containment))
    monkeypatch.setattr(triangulation, "_segments_intersect", lambda *_args: False)
    monkeypatch.setattr(triangulation, "_point_on_segment", lambda *_args: True)
    assert not triangulation._bridge_visible_between_loops(0, 3, loops, points)


def test_area_ray_and_bridge_fallback_helpers_cover_degenerate_geometry():
    assert triangulation._signed_polygon_area2([(0.0, 0.0), (1.0, 0.0)]) == 0.0
    points = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]
    assert triangulation._ray_bridge_target(2, [0, 1], points) is None
    assert triangulation._find_bridge_target(2, [0, 1], points) == 1

    collinear = [(0.0, 0.0), (4.0, 0.0), (2.0, 0.0)]
    assert triangulation._has_collinear_better(0, 1, [1, 2], collinear, 0.0, 0.0)


def test_best_visible_bridge_prefers_less_reused_candidate(monkeypatch):
    points = [(2.0, 0.0), (3.0, 1.0), (4.0, 0.0)]
    monkeypatch.setattr(triangulation, "_segment_visible", lambda *_args: True)
    assert triangulation._best_visible_bridge_target(0, [1, 2], points, 0, True, Counter({1: 2, 2: 1})) == 1


def test_ear_helpers_cover_short_triangle_fan_and_degenerate_quality():
    points = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    assert triangulation._fan_triangles([0, 1, 2, 3]) == [(0, 1, 2), (0, 2, 3)]
    assert triangulation._ear_clip([0, 1], points) == []
    assert triangulation._ear_clip([0, 1, 2], points) == [(0, 1, 2)]
    assert triangulation._ear_clip([3, 2, 1, 0], points) == [
        (3, 2, 1),
        (3, 1, 0),
    ]
    assert triangulation._triangle_shape_quality((0.0, 0.0), (0.0, 0.0), (0.0, 0.0)) == 0.0


def test_ear_rejects_a_diagonal_that_crosses_an_unrelated_edge(monkeypatch):
    points = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (2.0, 2.0), (-1.0, 2.0)]
    monkeypatch.setattr(triangulation, "_point_in_triangle", lambda *_args: False)
    monkeypatch.setattr(triangulation, "_segments_intersect", lambda *_args: True)
    assert not triangulation._is_ear(0, 1, 2, [0, 1, 2, 3, 4], points)
