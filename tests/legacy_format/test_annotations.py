# SPDX-License-Identifier: MIT
"""Text, dimensions, and construction annotation decoding."""

# ruff: noqa: F403, F405

from ._fixtures import *


def test_read_supported_object_dispatches_text() -> None:
    """Dispatch CText v9 and preserve text, font, anchor, and placement fields."""
    data = b"".join(
        [
            _new_class_tag("CText", schema=9),
            _drawing_element_payload_bytes(),
            _new_class_tag("CSkFont", schema=1),
            b"\x00\x00",
            _font_preview_payload_bytes("Arial"),
            struct.pack("<d", 0.25),
            struct.pack("<d", 0.5),
            _point_ref_preview_bytes(),
            struct.pack("<3d", 1.0, 2.0, 3.0),
            struct.pack("<3d", 0.0, 0.0, 1.0),
            struct.pack("<I", 2),
            struct.pack("<I", 3),
            b"\x01\x00",
            struct.pack("<I", 4),
            b"\x01",
            _legacy_string("Label"),
            b"\x00",
            struct.pack("<I", 5),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CText": 9,
            "CSkFont": 1,
        },
    )

    assert preview.font is not None
    assert preview.font.face_name == "Arial"
    assert (preview.screen_x, preview.screen_y) == (0.25, 0.5)
    point_ref = preview.point_ref
    assert point_ref.kind == 1
    assert point_ref.position == (1.0, 2.0, 3.0)
    assert point_ref.leaf_tag.kind == "null"
    assert preview.leader_vector == (1.0, 2.0, 3.0)
    assert preview.view_direction == (0.0, 0.0, 1.0)
    assert (
        preview.leader_type,
        preview.line_weight,
        preview.arrow_type,
        preview.hidden_leader_direction,
    ) == (
        2,
        3,
        4,
        5,
    )
    assert (
        preview.point_ref_front,
        preview.hide_out_of_plane,
        preview.display_leader,
        preview.convert_to_screen_on_explode,
    ) == (
        True,
        False,
        True,
        False,
    )
    assert preview.text == "Label"
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_dimension_style() -> None:
    """Dispatch CDimensionStyle v4 and preserve all confirmed style fields."""
    data = b"".join(
        [
            _new_class_tag("CDimensionStyle", schema=4),
            b"\x00\x00",
            struct.pack("<I", 0),
            _new_class_tag("CSkFont", schema=1),
            b"\x00\x00",
            _font_preview_payload_bytes("Arial"),
            b"\x01\x00",
            struct.pack("<IIIII", 10, 11, 12, 13, 14),
            b"\x01",
            _rgba(10, 20, 30, 255),
            b"\x00\x01",
            struct.pack("<d", 1.25),
            b"\x00",
            struct.pack("<d", 2.5),
            _rgba(40, 50, 60, 255),
            _rgba(70, 80, 90, 255),
            struct.pack("<I", 15),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CDimensionStyle": 4,
            "CSkFont": 1,
        },
    )

    assert isinstance(preview, DimensionStyle)
    assert preview.font_ref == 4
    assert preview.text_3d is True
    assert preview.always_readable is False
    assert preview.extension_offset == 10
    assert preview.extension_overshoot == 11
    assert preview.line_weight == 12
    assert preview.arrow_type == 13
    assert preview.arrow_size == 14
    assert preview.highlight_non_associative is True
    assert preview.highlight_non_associative_color == 0xFF0A141E
    assert preview.show_radial_diameter_prefix is False
    assert preview.hide_out_of_plane is True
    assert preview.hide_out_of_plane_value == 1.25
    assert preview.hide_small is False
    assert preview.hide_small_value == 2.5
    assert preview.color == 0xFF28323C
    assert preview.text_color == 0xFF46505A
    assert preview.text_position == 15
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_dimension_base() -> None:
    """Dispatch CDimension v1 and preserve common annotation fields."""
    data = b"".join(
        [
            _new_class_tag("CDimension", schema=1),
            _drawing_element_payload_bytes(),
            _legacy_string("Length"),
            _new_class_tag("CSkFont", schema=1),
            b"\x00\x00",
            _font_preview_payload_bytes("Arial"),
            b"\x01",
            struct.pack("<I", 9),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CDimension": 1,
            "CSkFont": 1,
        },
    )

    assert preview.text == "Length"
    assert preview.font is not None
    assert preview.font.face_name == "Arial"
    assert preview.is_3d_text is True
    assert preview.arrow_type == 9
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_dimension_radial() -> None:
    """Dispatch CDimensionRadial v2 with inline arc data when target is null."""
    data = b"".join(
        [
            _new_class_tag("CDimensionRadial", schema=2),
            _dimension_base_payload_bytes(text="Radius"),
            b"\x00\x00",
            struct.pack("<d", 1.5),
            struct.pack("<d", 2.5),
            b"\x01",
            _arc3d_preview_payload_bytes(),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CDimension": 1,
            "CDimensionRadial": 2,
        },
    )

    assert preview.dimension.text == "Radius"
    assert preview.target_tag.kind == "null"
    assert preview.target is None
    assert preview.parameter == 1.5
    assert preview.radius_ratio == 2.5
    assert preview.is_diameter is True
    assert preview.arc is not None
    assert preview.arc[0] == (1.0, 2.0, 3.0)
    assert preview.arc[5] == (0.0, 1.0, 0.0)
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_construction_geometry() -> None:
    """Dispatch the CConstructionGeometry v0 base payload."""
    data = b"".join(
        [
            _new_class_tag("CConstructionGeometry", schema=0),
            _drawing_element_payload_bytes(),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CConstructionGeometry": 0,
        },
    )

    assert preview.material_tag.kind == "null"
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_polyline3d() -> None:
    """Dispatch CPolyline3d v0 with drawing element and point array."""
    data = b"".join(
        [
            _new_class_tag("CPolyline3d", schema=0),
            _drawing_element_payload_bytes(),
            struct.pack("<I", 2),
            struct.pack("<3d", 1.0, 2.0, 3.0),
            struct.pack("<3d", 4.0, 5.0, 6.0),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CPolyline3d": 0,
        },
    )

    drawing_element, points = preview
    assert drawing_element.material_tag.kind == "null"
    assert points == ((1.0, 2.0, 3.0), (4.0, 5.0, 6.0))
    assert session.tell() == len(data)
