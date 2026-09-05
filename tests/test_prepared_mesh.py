# SPDX-License-Identifier: MIT
import pytest

import skppy.data_structure.mesh_preparation as mesh_preparation
from skppy.data_structure.entities import (
    Edge,
    EdgeUse,
    Entities,
    Face,
    FaceUVProjection,
    Loop,
    UVPin,
    Vertex,
)
from skppy.data_structure.images import Texture
from skppy.data_structure.materials import Material
from skppy.data_structure.primitives import Vector2D, Vector3D
from skppy.data_structure.scene import PreparedFace, PreparedMesh


def _textured_quad(*, front_material_id=None, back_material_id=None):
    projection = FaceUVProjection(transform=[2.0, 0.0, 0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 1.0])
    entities = Entities(
        vertices=[
            Vertex(1, Vector3D(0.0, 0.0, 0.0)),
            Vertex(2, Vector3D(2.0, 0.0, 0.0)),
            Vertex(3, Vector3D(2.0, 2.0, 0.0)),
            Vertex(4, Vector3D(0.0, 2.0, 0.0)),
        ],
        edges=[
            Edge(10, 1, 2),
            Edge(11, 2, 3),
            Edge(12, 3, 4),
            Edge(13, 4, 1),
        ],
        faces=[
            Face(
                id=100,
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
                front_material_id=front_material_id,
                back_material_id=back_material_id,
            )
        ],
    )
    material = Material(
        id=7,
        name="Image",
        has_texture=True,
        texture=Texture(filename="image.png", x_scale=1.0, y_scale=1.0),
    )
    return entities, entities.faces[0], material, projection


def test_prepare_mesh_preserves_projection_with_inherited_material():
    entities, face, material, projection = _textured_quad()
    face.front_uv = projection

    prepared = entities.prepare_mesh(
        "inherited projection",
        {material.id: material},
        inherited_material_id=material.id,
    )

    assert prepared.faces[0].vertex_uvs == [
        (0.0, 0.0),
        (1.0, 0.0),
        (1.0, 1.0),
        (0.0, 1.0),
    ]


def test_prepare_mesh_preserves_face_layer_id() -> None:
    """Carry source tag ownership into renderer-neutral mesh data."""
    entities, face, _, _ = _textured_quad()
    face.layer_id = 42

    prepared = entities.prepare_mesh("layered", {})

    assert prepared.faces[0].layer_id == 42


@pytest.mark.parametrize(
    "slot", ["metallic_texture", "roughness_texture", "normal_texture", "bump_texture", "displacement_texture"]
)
def test_renderer_only_material_has_scaled_uvs(slot: str) -> None:
    entities, _, material, _ = _textured_quad(front_material_id=7)
    material.texture = None
    material.has_texture = False
    setattr(material, slot, Texture(filename="map.png", x_scale=2.0, y_scale=4.0))

    indexed = entities.prepare_mesh("renderer only", {7: material}).to_indexed()

    assert indexed.face_uvs == [[(0.0, 0.0), (1.0, 0.0), (1.0, 0.5), (0.0, 0.5)]]


def test_prepare_mesh_uses_other_side_projection_for_same_material():
    entities, face, material, projection = _textured_quad(
        front_material_id=7,
        back_material_id=7,
    )
    face.back_uv = projection

    prepared = entities.prepare_mesh("shared material", {material.id: material})

    assert prepared.faces[0].vertex_uvs == [
        (0.0, 0.0),
        (1.0, 0.0),
        (1.0, 1.0),
        (0.0, 1.0),
    ]


def test_face_material_mapping_prefers_distinct_front_appearance() -> None:
    _, face, _, front_projection = _textured_quad(
        front_material_id=7,
        back_material_id=8,
    )
    back_projection = FaceUVProjection(transform=[3.0, 0.0, 0.0, 0.0, 3.0, 0.0, 0.0, 0.0, 1.0])
    face.front_uv = front_projection
    face.back_uv = back_projection

    material_id, projection = face.resolve_material_mapping(9)

    assert material_id == 7
    assert projection is front_projection


def test_face_material_mapping_uses_back_when_front_is_unpainted() -> None:
    _, face, _, _ = _textured_quad(back_material_id=8)
    back_projection = FaceUVProjection()
    face.back_uv = back_projection

    material_id, projection = face.resolve_material_mapping(9)

    assert material_id == 8
    assert projection is back_projection


def test_face_material_mapping_uses_projection_with_inherited_material() -> None:
    _, face, _, _ = _textured_quad()
    inherited_projection = FaceUVProjection()
    face.back_uv = inherited_projection

    material_id, projection = face.resolve_material_mapping(9)

    assert material_id == 9
    assert projection is inherited_projection


def test_prepare_mesh_preserves_exact_texture_control_point_uv() -> None:
    entities, face, material, projection = _textured_quad(front_material_id=7)
    projection.pins.append(
        UVPin(
            texture_position=Vector2D(4.0, 3.0),
            model_position=Vector2D(2.0, 0.0),
        )
    )
    face.front_uv = projection

    prepared = entities.prepare_mesh("positioned texture", {material.id: material})

    assert prepared.faces[0].vertex_uvs == [
        (0.0, 0.0),
        (4.0, 3.0),
        (1.0, 1.0),
        (0.0, 1.0),
    ]


def test_to_indexed_merges_positions_but_preserves_loop_uvs():
    mesh = PreparedMesh(
        name="two_faces",
        faces=[
            PreparedFace(
                vertex_positions=[(0, 0, 0), (1, 0, 0), (1, 1, 0)],
                vertex_uvs=[(0, 0), (1, 0), (1, 1)],
                normal=(0, 0, 1),
                material_name="A",
                material_id=10,
                source_face_id=100,
                edge_ids=[1, 2, 3],
                edge_flags=[0x04, 0, 0x04],
            ),
            PreparedFace(
                vertex_positions=[(0, 0, 0), (1, 1, 0), (0, 1, 0)],
                vertex_uvs=[(0.25, 0.25), (0.75, 0.75), (0, 1)],
                normal=(0, 0, 1),
                material_name="B",
                material_id=20,
                source_face_id=200,
                edge_ids=[4, 5, 6],
                edge_flags=[0, 0x04, 0],
            ),
        ],
    )

    indexed = mesh.to_indexed(merge_vertices=True)

    assert indexed.vertex_positions == [
        (0, 0, 0),
        (1, 0, 0),
        (1, 1, 0),
        (0, 1, 0),
    ]
    assert indexed.faces == [[0, 1, 2], [0, 2, 3]]
    assert indexed.face_uvs == [
        [(0, 0), (1, 0), (1, 1)],
        [(0.25, 0.25), (0.75, 0.75), (0, 1)],
    ]
    assert indexed.face_material_names == ["A", "B"]
    assert indexed.face_material_ids == [10, 20]
    assert indexed.source_face_ids == [100, 200]
    assert indexed.face_edge_ids == [[1, 2, 3], [4, 5, 6]]
    assert indexed.face_edge_flags == [[0x04, 0, 0x04], [0, 0x04, 0]]


def test_prepared_face_rejects_misaligned_or_non_finite_corner_data() -> None:
    """Fail at the public mesh boundary instead of inside an importer."""
    with pytest.raises(ValueError, match="vertex_uvs must contain 3 entries"):
        PreparedFace(
            vertex_positions=[(0, 0, 0), (1, 0, 0), (0, 1, 0)],
            vertex_uvs=[(0, 0)],
            normal=(0, 0, 1),
            material_name=None,
        )

    with pytest.raises(ValueError, match="finite"):
        PreparedFace(
            vertex_positions=[(0, 0, 0), (1, 0, 0), (0, float("inf"), 0)],
            vertex_uvs=None,
            normal=(0, 0, 1),
            material_name=None,
        )


def test_to_indexed_triangulates_ngon_and_copies_face_metadata():
    mesh = PreparedMesh(
        name="quad",
        faces=[
            PreparedFace(
                vertex_positions=[(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
                vertex_uvs=[(0, 0), (1, 0), (1, 1), (0, 1)],
                normal=(0, 0, 1),
                material_name="Tile",
                material_id=7,
                source_face_id=42,
                edge_ids=[11, 12, 13, 14],
                edge_flags=[0x04, 0, 0x04, 0],
            )
        ],
    )

    indexed = mesh.to_indexed(triangulate=True)

    assert len(indexed.faces) == 2
    assert all(len(face) == 3 for face in indexed.faces)
    assert indexed.face_material_names == ["Tile", "Tile"]
    assert indexed.face_material_ids == [7, 7]
    assert indexed.source_face_ids == [42, 42]
    assert all(uvs is not None and len(uvs) == 3 for uvs in indexed.face_uvs)
    flattened_ids = [edge_id for face in indexed.face_edge_ids for edge_id in face]
    flattened_flags = [flag for face in indexed.face_edge_flags for flag in face]
    assert sorted(edge_id for edge_id in flattened_ids if edge_id is not None) == [
        11,
        12,
        13,
        14,
    ]
    assert flattened_ids.count(None) == 2
    assert flattened_flags.count(0x04) == 2


def test_prepare_mesh_can_split_single_hole_face_into_ngons():
    entities = Entities(
        vertices=[
            Vertex(1, Vector3D(0.0, 0.0, 0.0)),
            Vertex(2, Vector3D(4.0, 0.0, 0.0)),
            Vertex(3, Vector3D(4.0, 4.0, 0.0)),
            Vertex(4, Vector3D(0.0, 4.0, 0.0)),
            Vertex(5, Vector3D(1.0, 1.0, 0.0)),
            Vertex(6, Vector3D(1.0, 3.0, 0.0)),
            Vertex(7, Vector3D(3.0, 3.0, 0.0)),
            Vertex(8, Vector3D(3.0, 1.0, 0.0)),
        ],
        edges=[
            Edge(10, 1, 2),
            Edge(11, 2, 3),
            Edge(12, 3, 4),
            Edge(13, 4, 1),
            Edge(14, 5, 6),
            Edge(15, 6, 7),
            Edge(16, 7, 8),
            Edge(17, 8, 5),
        ],
        faces=[
            Face(
                id=100,
                plane=(0.0, 0.0, 1.0, 0.0),
                outer_loop=Loop(
                    [
                        EdgeUse(10, False),
                        EdgeUse(11, False),
                        EdgeUse(12, False),
                        EdgeUse(13, False),
                    ]
                ),
                inner_loops=[
                    Loop(
                        [
                            EdgeUse(14, False),
                            EdgeUse(15, False),
                            EdgeUse(16, False),
                            EdgeUse(17, False),
                        ]
                    )
                ],
            )
        ],
    )

    triangulated = entities.prepare_mesh("hole", {})
    assert len(triangulated.faces) > 2
    assert all(len(face.vertex_positions) == 3 for face in triangulated.faces)

    prepared = entities.prepare_mesh("hole", {}, split_holes_to_ngons=True)
    indexed = prepared.to_indexed(merge_vertices=True)

    assert len(indexed.faces) == 2
    assert all(len(face) == 6 for face in indexed.faces)
    assert indexed.source_face_ids == [100, 100]
    assert all(edge_ids.count(None) == 2 for edge_ids in indexed.face_edge_ids)


def test_prepare_mesh_merges_multiple_hole_triangles_into_ngons(monkeypatch):
    vertices = [
        Vertex(1, Vector3D(0.0, 0.0, 0.0)),
        Vertex(2, Vector3D(10.0, 0.0, 0.0)),
        Vertex(3, Vector3D(10.0, 6.0, 0.0)),
        Vertex(4, Vector3D(0.0, 6.0, 0.0)),
        Vertex(5, Vector3D(2.0, 2.0, 0.0)),
        Vertex(6, Vector3D(2.0, 4.0, 0.0)),
        Vertex(7, Vector3D(4.0, 4.0, 0.0)),
        Vertex(8, Vector3D(4.0, 2.0, 0.0)),
        Vertex(9, Vector3D(6.0, 2.0, 0.0)),
        Vertex(10, Vector3D(6.0, 4.0, 0.0)),
        Vertex(11, Vector3D(8.0, 4.0, 0.0)),
        Vertex(12, Vector3D(8.0, 2.0, 0.0)),
    ]
    edges = [
        Edge(10, 1, 2),
        Edge(11, 2, 3),
        Edge(12, 3, 4),
        Edge(13, 4, 1),
        Edge(14, 5, 6),
        Edge(15, 6, 7),
        Edge(16, 7, 8),
        Edge(17, 8, 5),
        Edge(18, 9, 10),
        Edge(19, 10, 11),
        Edge(20, 11, 12),
        Edge(21, 12, 9),
    ]
    face = Face(
        id=200,
        plane=(0.0, 0.0, 1.0, 0.0),
        outer_loop=Loop(
            [
                EdgeUse(10, False),
                EdgeUse(11, False),
                EdgeUse(12, False),
                EdgeUse(13, False),
            ]
        ),
        inner_loops=[
            Loop(
                [
                    EdgeUse(14, False),
                    EdgeUse(15, False),
                    EdgeUse(16, False),
                    EdgeUse(17, False),
                ]
            ),
            Loop(
                [
                    EdgeUse(18, False),
                    EdgeUse(19, False),
                    EdgeUse(20, False),
                    EdgeUse(21, False),
                ]
            ),
        ],
    )
    entities = Entities(vertices=vertices, edges=edges, faces=[face])

    triangulated = entities.prepare_mesh("multiple holes", {})
    merged = entities.prepare_mesh("multiple holes", {}, split_holes_to_ngons=True)

    assert len(merged.faces) < len(triangulated.faces)
    assert any(len(prepared_face.vertex_positions) > 3 for prepared_face in merged.faces)
    assert all(prepared_face.source_face_id == 200 for prepared_face in merged.faces)
    assert all(len(prepared_face.edge_ids) == len(prepared_face.vertex_positions) for prepared_face in merged.faces)

    monkeypatch.setattr(mesh_preparation, "_MAX_NGON_MERGE_TRIANGLES", 0)
    bounded = entities.prepare_mesh("multiple holes", {}, split_holes_to_ngons=True)
    assert bounded.faces == triangulated.faces
