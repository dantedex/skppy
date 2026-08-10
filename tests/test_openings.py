# SPDX-License-Identifier: MIT
"""Cutting-component opening inference and prepared-mesh integration."""

import math

import pytest

from skppy.data_structure.entities import ComponentDefinition, ComponentInstance, Edge, Entities, Vertex
import skppy.data_structure.openings as opening_helpers
from skppy.data_structure.openings import infer_cutting_openings
from skppy.data_structure.primitives import Transform, Vector3D


def _cutting_definition() -> ComponentDefinition:
    definition = ComponentDefinition(id=20, name="Cutting window", behavior_cuts_opening=True)
    definition.entities.add_face([(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 2.0, 0.0), (0.0, 2.0, 0.0)])
    return definition


def _triangle_area(points):
    first, second, third = points
    ab = tuple(second[index] - first[index] for index in range(3))
    ac = tuple(third[index] - first[index] for index in range(3))
    cross = (
        ab[1] * ac[2] - ab[2] * ac[1],
        ab[2] * ac[0] - ab[0] * ac[2],
        ab[0] * ac[1] - ab[1] * ac[0],
    )
    return 0.5 * math.sqrt(sum(value * value for value in cross))


@pytest.mark.parametrize(("translation", "expected_area"), [((2.0, 2.0, 0.0), 96.0), ((8.5, 2.0, 0.0), 97.0)])
def test_cutting_component_contour_removes_host_face_area(translation, expected_area):
    host = Entities()
    face = host.add_face([(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0), (0.0, 10.0, 0.0)])
    cutting = _cutting_definition()
    host.add_instance(cutting, transform=Transform.from_translation(*translation))

    openings = infer_cutting_openings(host, {cutting.id: cutting})
    prepared = host.prepare_mesh("host", {}, opening_positions_by_face_id=openings)

    assert list(openings) == [face.id]
    assert len(openings[face.id][0]) == 4
    assert sum(_triangle_area(item.vertex_positions) for item in prepared.faces) == pytest.approx(expected_area)


def test_opening_inference_ignores_unknown_non_cutting_and_empty_definitions():
    host = Entities(
        component_instances=[
            ComponentInstance(id=1, definition_id=100),
            ComponentInstance(id=2, definition_id=101),
            ComponentInstance(id=3, definition_id=102),
        ]
    )
    ordinary = ComponentDefinition(id=101, behavior_cuts_opening=False)
    empty_cut = ComponentDefinition(id=102, behavior_cuts_opening=True)

    assert infer_cutting_openings(host, {ordinary.id: ordinary, empty_cut.id: empty_cut}) == {}


def test_cutting_outline_rejects_unusable_planar_graphs():
    nonplanar = ComponentDefinition(
        entities=Entities(
            vertices=[Vertex(1, Vector3D(0.0, 0.0, 1.0)), Vertex(2, Vector3D(1.0, 0.0, 1.0))],
            edges=[Edge(3, 1, 2)],
        )
    )
    single_edge = ComponentDefinition(
        entities=Entities(
            vertices=[Vertex(1, Vector3D(0.0, 0.0, 0.0)), Vertex(2, Vector3D(1.0, 0.0, 0.0))],
            edges=[Edge(3, 1, 2)],
        )
    )

    assert opening_helpers._cutting_outline(nonplanar) == []
    assert opening_helpers._cutting_outline(single_edge) == []


def test_host_face_selection_rejects_wrong_planes_outside_centroids_and_concave_clips(monkeypatch):
    contour = [(0.2, 0.2, 0.0), (1.2, 0.2, 0.0), (1.2, 1.2, 0.0), (0.2, 1.2, 0.0)]
    square = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 2.0, 0.0), (0.0, 2.0, 0.0)]
    assert opening_helpers._find_host_face(contour, [(1, (0.0, 0.0, 1.0, -1.0), square)]) is None
    shifted = [(3.0 + x, y, z) for x, y, z in square]
    assert opening_helpers._find_host_face(contour, [(1, (0.0, 0.0, 1.0, 0.0), shifted)]) is None

    concave = [(0.0, 0.0, 0.0), (3.0, 0.0, 0.0), (3.0, 1.0, 0.0), (1.0, 1.0, 0.0), (1.0, 3.0, 0.0), (0.0, 3.0, 0.0)]
    partial = [(0.1, 0.1, 0.0), (1.2, 0.1, 0.0), (1.2, 1.2, 0.0), (0.1, 1.2, 0.0)]
    assert opening_helpers._find_host_face(partial, [(1, (0.0, 0.0, 1.0, 0.0), concave)]) is None

    monkeypatch.setattr(opening_helpers, "_clip_to_convex_polygon", lambda *_args: [])
    unit_square = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
    assert opening_helpers._find_host_face(partial, [(1, (0.0, 0.0, 1.0, 0.0), unit_square)]) is None


def test_polygon_helpers_cover_boundary_and_fully_clipped_subject():
    square = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]
    outside = [(3.0, 3.0), (4.0, 3.0), (4.0, 4.0), (3.0, 4.0)]
    assert opening_helpers._point_in_polygon((0.0, 0.0), square, include_boundary=True)
    assert opening_helpers._clip_to_convex_polygon(outside, square) == []
