# SPDX-License-Identifier: MIT
import math

import pytest

from skppy import Transform, Vector2D, Vector3D
from skppy.data_structure.entities import Edge, EdgeUse, Entities, Face, Loop, Vertex
from skppy.utils import (
    inches_to_meters,
    meters_to_inches,
    transform_to_matrix4x4,
    triangulate_face,
)


def test_transform_to_matrix4x4_preserves_public_list_api():
    matrix = transform_to_matrix4x4([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 1.0])

    assert isinstance(matrix, list)
    assert all(isinstance(row, list) for row in matrix)
    assert matrix == [
        [1.0, 2.0, 3.0, 10.0],
        [4.0, 5.0, 6.0, 11.0],
        [7.0, 8.0, 9.0, 12.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def test_transform_uses_numpy_matrix_internally_and_serializes_to_13_values():
    transform = Transform.from_translation(10.0, 20.0, 30.0)

    assert transform.matrix.shape == (4, 4)
    assert transform.to_list() == [
        1.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        1.0,
        10.0,
        20.0,
        30.0,
        1.0,
    ]
    assert transform.translation().to_tuple() == (10.0, 20.0, 30.0)


def test_transform_matrix_property_returns_copy():
    transform = Transform.identity()
    matrix = transform.matrix
    matrix[0, 3] = 99.0

    assert transform.to_list()[9] == 0.0


def test_transform_rotation_serializes_from_numpy_matrix():
    transform = Transform.from_rotation_z(math.pi / 2)

    assert transform.to_list() == pytest.approx(
        [
            0.0,
            -1.0,
            0.0,
            1.0,
            0.0,
            0.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            0.0,
            1.0,
        ],
        abs=1e-12,
    )


def test_vector_helpers_use_numpy_compatible_arrays():
    v = Vector3D(1.0, 2.0, 3.0)
    other = Vector3D(4.0, 5.0, 6.0)

    assert Vector2D(1.0, 2.0).to_array().tolist() == [1.0, 2.0]
    assert v.to_array().tolist() == [1.0, 2.0, 3.0]
    assert v.dot(other) == 32.0
    assert v.cross(other).to_tuple() == (-3.0, 6.0, -3.0)
    assert v.length() == pytest.approx(math.sqrt(14.0))


def test_unit_conversion_helpers_are_inverse():
    assert inches_to_meters(39.3700787402) == pytest.approx(1.0)
    assert meters_to_inches(2.0) == pytest.approx(78.7401574804)
    assert meters_to_inches(inches_to_meters(123.45)) == pytest.approx(123.45)


def test_transform_constructors_equality_and_degenerate_inputs():
    assert Transform.from_uniform_scale(2.0).to_list()[:9] == [
        2.0,
        0.0,
        0.0,
        0.0,
        2.0,
        0.0,
        0.0,
        0.0,
        2.0,
    ]
    assert Transform.from_scale(2.0, 3.0, 4.0).to_list()[:9] == [
        2.0,
        0.0,
        0.0,
        0.0,
        3.0,
        0.0,
        0.0,
        0.0,
        4.0,
    ]
    assert Transform.from_rotation_x(math.pi / 2).to_list()[4:9] == pytest.approx(
        [0.0, -1.0, 0.0, 1.0, 0.0],
        abs=1e-12,
    )
    assert Transform.from_rotation_y(math.pi / 2).to_list()[:9] == pytest.approx(
        [0.0, 0.0, 1.0, 0.0, 1.0, 0.0, -1.0, 0.0, 0.0],
        abs=1e-12,
    )
    assert Transform([1.0, 2.0, 3.0]).to_list() == [
        1.0,
        2.0,
        3.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
    ]
    assert Transform([1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 4.0, 5.0, 6.0]).to_list()[-1] == 1.0
    assert Transform.identity() == Transform()
    assert Transform.identity() != object()


def test_vector_arithmetic_and_zero_normalization():
    assert (Vector2D(3.0, 4.0) + Vector2D(1.0, 2.0)).to_array().tolist() == [
        4.0,
        6.0,
    ]
    assert (Vector2D(3.0, 4.0) - Vector2D(1.0, 2.0)).to_array().tolist() == [
        2.0,
        2.0,
    ]
    assert (Vector3D(3.0, 4.0, 5.0) + Vector3D(1.0, 2.0, 3.0)).to_tuple() == (
        4.0,
        6.0,
        8.0,
    )
    assert (Vector3D(3.0, 4.0, 5.0) - Vector3D(1.0, 2.0, 3.0)).to_tuple() == (
        2.0,
        2.0,
        2.0,
    )
    assert (Vector3D(1.0, 2.0, 3.0) * 2.0).to_tuple() == (2.0, 4.0, 6.0)
    assert (3.0 * Vector3D(1.0, 2.0, 3.0)).to_tuple() == (3.0, 6.0, 9.0)
    assert Vector3D(0.0, 0.0, 0.0).normalized().to_tuple() == (0, 0, 1)


def test_loop_and_face_triangulation_helpers_cover_reversed_and_missing_edges():
    loop = Loop(
        [
            EdgeUse(10, False),
            EdgeUse(11, True),
            EdgeUse(999, False),
            EdgeUse(12, False),
        ]
    )
    edge_map = {10: (1, 2), 11: (3, 2), 12: (3, 1)}

    assert loop.vertex_ids(edge_map) == [1, 2, 3]

    entities = Entities(
        vertices=[
            Vertex(1, Vector3D(0.0, 0.0, 0.0)),
            Vertex(2, Vector3D(1.0, 0.0, 0.0)),
            Vertex(3, Vector3D(1.0, 1.0, 0.0)),
            Vertex(4, Vector3D(0.0, 1.0, 0.0)),
        ],
        edges=[Edge(10, 1, 2), Edge(11, 2, 3), Edge(12, 3, 4), Edge(13, 4, 1)],
    )
    face = Face(
        id=20,
        plane=(0.0, 0.0, 1.0, 0.0),
        outer_loop=Loop(
            [
                EdgeUse(10, False),
                EdgeUse(11, False),
                EdgeUse(12, False),
                EdgeUse(13, False),
            ]
        ),
        inner_loops=[],
    )

    assert triangulate_face(face, entities) == [(1, 2, 3), (1, 3, 4)]
    assert (
        triangulate_face(
            Face(21, (0.0, 0.0, 1.0, 0.0), Loop([EdgeUse(10, False)]), []),
            entities,
        )
        == []
    )
