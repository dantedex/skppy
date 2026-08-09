# SPDX-License-Identifier: MIT
"""Face graph decoding and root geometry integration."""

# ruff: noqa: F403, F405

from ._fixtures import *

from skppy.data_structure.entities import FaceUVProjection, Loop
from skppy.parser_legacy.geometry_payloads import read_drawing_element_body
from skppy.parser_legacy.geometry_readers import _apply_face_texture_coords
from skppy.parser_legacy.parser_types import DrawingElementState, EntityHeaderState


@pytest.mark.parametrize("class_version", [0, 1, 3, 4, 5])
def test_drawing_element_old_schemas_preserve_shadow_defaults(
    class_version: int,
) -> None:
    """Apply observed defaults when shadow fields are absent."""
    payload = b"" if class_version == 0 else b"\x00"
    if class_version > 3:
        payload += b"\x00\x00"

    body = read_drawing_element_body(LegacyArchiveReader(io.BytesIO(payload)), class_version)

    assert body[:6] == (False, True, True, False, False, False)


def test_drawing_element_v9_decodes_named_flags_in_sdk_order() -> None:
    """Decode hidden, shadow, shading, and lock flags without a packed mask."""
    payload = b"\x01\x00\x01\x01\x00\x01\x00\x00"

    body = read_drawing_element_body(LegacyArchiveReader(io.BytesIO(payload)), 9)

    assert body[:6] == (True, False, True, True, False, True)
    assert body[6] is not None
    assert body[6].kind == "null"


def test_read_edge_use_preview_preserves_references() -> None:
    """Decode CEdgeUse references without requiring target objects inline."""
    data = b"".join(
        [
            _new_class_tag("CEdgeUse", schema=1),
            b"\x00\x00",
            _object_ref_tag(11),
            b"\x01",
            _object_ref_tag(12),
        ]
    )

    edge_use = read_edge_use_preview(io.BytesIO(data), entity_class_version=3, edge_use_class_version=1)

    assert edge_use.edge_id == 11
    assert edge_use.reversed is True


def test_read_loop_preview_preserves_edge_use_refs() -> None:
    """Decode CLoop flags and its null-terminated edge-use references."""
    data = b"".join(
        [
            _new_class_tag("CLoop", schema=1),
            b"\x00\x00",
            b"\x01",
            b"\x00",
            _object_ref_tag(21),
            _object_ref_tag(22),
            b"\x00\x00",
        ]
    )

    loop = read_loop_preview(io.BytesIO(data), entity_class_version=3)

    assert loop.edge_uses == []


def test_read_face_preview_preserves_loop_and_material_refs() -> None:
    """Decode CFace plane, loop refs, and back-material ref."""
    data = b"".join(
        [
            _new_class_tag("CFace", schema=3),
            _drawing_element_payload_bytes(),
            struct.pack("<4d", 0.0, 0.0, 1.0, 0.0),
            struct.pack("<I", 1),
            _object_ref_tag(31),
            _object_ref_tag(32),
        ]
    )

    face = read_face_preview(io.BytesIO(data), entity_class_version=3, face_class_version=3)

    assert face.plane == (0.0, 0.0, 1.0, 0.0)
    assert face.outer_loop.edge_uses == []
    assert face.back_material_id == 32


def test_face_uses_texture_coordinates_from_its_attribute_container() -> None:
    """Associate CFaceTextureCoords with the owning shared Face object."""
    session = LegacyArchiveSession(io.BytesIO())
    container_index = session.index_table.register_object("CAttributeContainer", 0)
    texture_index = session.index_table.register_object("CFaceTextureCoords", 4)
    texture_tag = ArchiveObjectTag(
        "object_ref",
        0,
        index=texture_index,
        schema=4,
        class_name="CFaceTextureCoords",
    )
    front_uv = FaceUVProjection(
        transform=list(_identity_matrix3_values()),
        origin=(0.0, 0.0, 1.0),
    )
    back_uv = FaceUVProjection(
        transform=list(_identity_matrix3_values()),
        origin=(0.0, 0.0, -1.0),
    )
    session.store_object(
        container_index,
        (ArchiveObjectTag("object_ref", 0), (texture_tag,), (), 0, 0),
    )
    session.store_object(
        texture_index,
        (0, front_uv, back_uv, 1, 0),
    )
    entity_header = EntityHeaderState(
        class_version=3,
        payload_start_offset=0,
        legacy_flags_u32=None,
        attribute_container_tag=None,
        persistent_id=None,
        header_end_offset=0,
        attribute_container_object_index=container_index,
    )
    drawing_element = DrawingElementState(
        payload_start_offset=0,
        entity_header=entity_header,
        material_tag=ArchiveObjectTag("null", 0, 0),
        hidden=False,
        casts_shadows=False,
        receives_shadows=False,
        soft=False,
        smooth=False,
        locked=False,
        layer_tag=None,
        payload_end_offset=0,
    )
    face = Face(
        id=1,
        plane=(0.0, 0.0, 1.0, 0.0),
        outer_loop=Loop([]),
        inner_loops=[],
    )

    _apply_face_texture_coords(
        SimpleNamespace(session=session),
        face,
        drawing_element,
    )

    assert face.front_uv is front_uv
    assert face.back_uv is None


def test_parse_legacy_header_decodes_supported_root_edge_preview() -> None:
    """Expose a simple root CEdge preview through the integrated V8 header."""
    data = _legacy_file_bytes(
        saved_path="C:/models/edge.skp",
        root_entity_count=1,
        root_entity_payload=_edge_preview_bytes(),
    )

    model = parse_legacy_bytes(data)
    legacy = model.legacy_archive

    assert len(model.entities.vertices) == 2
    assert len(model.entities.edges) == 1
    assert model.entities.vertices[0].position.to_tuple() == (0.0, 0.0, 0.0)
    assert model.entities.vertices[1].position.to_tuple() == (10.0, 10.0, 10.0)
    assert model.entities.edges[0].start_vertex_id == model.entities.vertices[0].id
    assert model.entities.edges[0].end_vertex_id == model.entities.vertices[1].id
    assert legacy is not None
    assert legacy.root_entity_count == 1
    assert len(legacy.root_edge_previews) == 1
    edge = legacy.root_edge_previews[0]
    assert model.entities.edges[0] is edge.edge
    assert model.entities.vertices[0] is edge.start_vertex
    assert model.entities.vertices[1] is edge.end_vertex
    assert edge.start_vertex.position.to_tuple() == (0.0, 0.0, 0.0)
    assert edge.end_vertex.position.to_tuple() == (10.0, 10.0, 10.0)
    assert legacy.archive_index_entries[12].class_name == "CVertex"
    assert legacy.archive_index_entries[13].class_name == "CVertex"
    assert legacy.model_tail_payload_end_offset is not None
    assert data[legacy.model_tail_payload_end_offset :] == b"ARCHIVE"


def test_parse_legacy_reuses_shared_curve_created_by_edge_reader() -> None:
    """Assign IDs to the same Curve cached by the legacy archive reader."""
    edge_payload = _edge_preview_with_curve_bytes().replace(_class_ref_tag(3), _new_class_tag("CVertex", schema=0), 1)
    model = parse_legacy_bytes(
        _legacy_file_bytes(
            saved_path="C:/models/curve.skp",
            root_entity_count=1,
            root_entity_payload=edge_payload,
        )
    )

    assert model.legacy_archive is not None
    archived_edge = model.legacy_archive.root_edge_previews[0]
    assert isinstance(archived_edge.curve, Curve)
    assert model.entities.curves == [archived_edge.curve]
    assert model.entities.edges[0].curve_id == archived_edge.curve.id


def test_parse_legacy_header_maps_supported_root_face_preview() -> None:
    """Map a nested root CFace preview into shared model entities."""
    data = _legacy_file_bytes(
        saved_path="C:/models/face.skp",
        root_entity_count=1,
        root_entity_payload=_nested_triangle_face_preview_bytes(),
    )

    model = parse_legacy_bytes(data)
    legacy = model.legacy_archive

    assert len(model.entities.vertices) == 3
    assert len(model.entities.edges) == 3
    assert len(model.entities.faces) == 1
    assert [vertex.position.to_tuple() for vertex in model.entities.vertices] == [
        (0.0, 0.0, 0.0),
        (10.0, 0.0, 0.0),
        (0.0, 10.0, 0.0),
    ]
    assert legacy is not None
    assert len(legacy.root_objects) == 1
    assert len(legacy.root_edge_previews) == 3
    assert len(legacy.root_faces) == 1
    face = legacy.root_faces[0]
    assert model.entities.faces[0] is face
    assert len(face.outer_loop.edge_uses) == 3
    assert {edge_use.edge_id for edge_use in face.outer_loop.edge_uses} == {edge.id for edge in model.entities.edges}
    prepared = model.entities.prepare_mesh("triangle", {})
    assert len(prepared.faces) == 1
    assert len(prepared.faces[0].vertex_positions) == 3


def test_parse_legacy_header_maps_root_construction_previews() -> None:
    """Map V8 construction point, line, and section-plane previews."""
    data = _legacy_file_bytes(
        saved_path="C:/models/construction.skp",
        root_entity_count=3,
        root_entity_payload=b"".join(
            [
                _new_class_tag("CConstructionPoint", schema=0),
                _drawing_element_payload_bytes(),
                struct.pack("<3d", 10.0, 20.0, 30.0),
                struct.pack("<3d", 1.0, 2.0, 3.0),
                b"\x01",
                _new_class_tag("CConstructionLine", schema=1),
                _drawing_element_payload_bytes(),
                struct.pack("<3d", 0.0, 0.0, 0.0),
                struct.pack("<3d", 1.0, 0.0, 0.0),
                struct.pack("<d", 0.0),
                struct.pack("<d", 100.0),
                struct.pack("<I", 0xAAAA),
                _new_class_tag("CSectionPlane", schema=3),
                _drawing_element_payload_bytes(),
                struct.pack("<4d", 0.0, 0.0, 1.0, 0.0),
            ]
        ),
    )

    model = parse_legacy_bytes(data)

    assert len(model.entities.guide_points) == 1
    assert len(model.entities.guide_lines) == 1
    assert len(model.entities.section_planes) == 1
    assert model.entities.guide_points[0].position.to_tuple() == (10.0, 20.0, 30.0)
    assert model.entities.guide_points[0].reference_point.to_tuple() == (1.0, 2.0, 3.0)
    assert model.entities.guide_lines[0].point.to_tuple() == (0.0, 0.0, 0.0)
    assert model.entities.guide_lines[0].direction.to_tuple() == (1.0, 0.0, 0.0)
    assert model.entities.guide_lines[0].stipple_pattern == 0xAAAA
    assert model.entities.section_planes[0].plane == (0.0, 0.0, 1.0, 0.0)
    assert model.legacy_archive is not None
    assert model.entities.guide_points[0] is model.legacy_archive.root_objects[0]
    assert model.entities.guide_lines[0] is model.legacy_archive.root_objects[1]
    assert model.entities.section_planes[0] is model.legacy_archive.root_objects[2]


def test_read_supported_object_dispatches_original_legacy_section_plane() -> None:
    """Decode V8 CSectionPlane v2 without the newer trailing state word."""
    data = b"".join(
        [
            _new_class_tag("CSectionPlane", schema=2),
            _drawing_element_payload_bytes(),
            struct.pack("<4d", 0.0, 1.0, 0.0, -4.0),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    section = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CDrawingElement": 9,
            "CSectionPlane": 2,
        },
    )

    assert isinstance(section, SectionPlane)
    assert section.plane == (0.0, 1.0, 0.0, -4.0)
    assert session.tell() == len(data)
