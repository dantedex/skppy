# SPDX-License-Identifier: MIT
"""Style, watermark, component, image, UV, and relationship objects."""

# ruff: noqa: F403, F405

from skppy.data_structure.primitives import Vector2D

from ._fixtures import *


def test_read_supported_object_dispatches_style() -> None:
    """Dispatch observed CSkpStyle payloads through the shared object path."""
    guid = bytes(range(16))
    data = _style_preview_payload_bytes(
        guid=guid,
        display_name="Style",
        file_name="classic.style",
        initial_file_name="fallback.style",
        option_count=53,
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(session, {"CEntity": 3, "CSkpStyle": 1})

    assert isinstance(preview, StyleDescriptor)
    assert preview.guid == guid
    assert preview.display_name == "Style"
    assert preview.file_name == "classic.style"
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_style_manager() -> None:
    """Dispatch CSkpStyleManager v2 with contained style references."""
    guid = bytes(range(16))
    data = b"".join(
        [
            _new_class_tag("CSkpStyleManager", schema=2),
            b"\x00\x00",
            struct.pack("<I", 1),
            _style_preview_payload_bytes(
                guid=guid,
                display_name="Style",
                file_name="classic.style",
            ),
            _object_ref_tag(4),
            _object_ref_tag(4),
            b"\x01",
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CSkpStyle": 1,
            "CSkpStyleManager": 2,
        },
    )

    assert isinstance(preview, StylesRegistry)
    assert len(preview.styles) == 1
    assert preview.styles[0].guid == guid
    assert preview.active_style_ref == 4
    assert preview.selected_style_dirty is True
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_watermark() -> None:
    """Dispatch CWatermark v1 with placement fields and embedded DIB."""
    data = _watermark_preview_payload_bytes(
        name="Watermark",
        path="watermark.png",
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CWatermark": 1,
            "CDib": 3,
        },
    )

    assert isinstance(preview, Watermark)
    assert preview.name == "Watermark"
    assert preview.position == 3
    assert preview.opacity == 0.75
    assert preview.image_data == b"PNG"
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_watermark_manager() -> None:
    """Dispatch CWatermarkManager v2 with contained watermark previews."""
    data = b"".join(
        [
            _new_class_tag("CWatermarkManager", schema=2),
            b"\x00\x00",
            struct.pack("<I", 1),
            _watermark_preview_payload_bytes(name="Overlay"),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CWatermark": 1,
            "CWatermarkManager": 2,
            "CDib": 3,
        },
    )

    assert isinstance(preview, WatermarkManager)
    assert preview.serialized_count == 1
    assert len(preview.watermarks) == 1
    assert preview.watermarks[0].name == "Overlay"
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_definition_list() -> None:
    """Dispatch CDefinitionList v0 component-definition reference arrays."""
    data = b"".join(
        [
            _new_class_tag("CDefinitionList", schema=0),
            struct.pack("<I", 2),
            b"\x00\x00",
            b"\x00\x00",
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CDefinitionList": 0,
        },
    )

    assert isinstance(preview, tuple)
    definition_tags, _, _ = preview
    assert [tag.kind for tag in definition_tags] == ["null", "null"]
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_component_instance() -> None:
    """Dispatch CComponentInstance v4 definition, transform, and name fields."""
    data = b"".join(
        [
            _new_class_tag("CComponentInstance", schema=4),
            _component_instance_payload_bytes(name="Instance 1"),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CComponentInstance": 4,
        },
    )

    assert isinstance(preview, ComponentInstance)
    assert preview.definition_id == 0
    assert preview.transform == list(_component_instance_transform_values())
    assert preview.name == "Instance 1"
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_group() -> None:
    """Dispatch CGroup v1 through the CComponentInstance base payload."""
    data = b"".join(
        [
            _new_class_tag("CGroup", schema=1),
            _component_instance_payload_bytes(name="Group 1"),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CComponentInstance": 4,
            "CGroup": 1,
        },
    )

    assert isinstance(preview, Group)
    assert preview.definition_id == 0
    assert preview.transform == list(_component_instance_transform_values())
    assert preview.name == "Group 1"
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_image() -> None:
    """Dispatch CImage v1 through the CComponentInstance base payload."""
    data = b"".join(
        [
            _new_class_tag("CImage", schema=1),
            _component_instance_payload_bytes(name="Image 1"),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CImage": 1,
            "CComponentInstance": 4,
        },
    )

    assert isinstance(preview, Image)
    assert preview.name == "Image 1"
    assert preview.definition_id == 0
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_background_image() -> None:
    """Dispatch CBackgroundImage v10 and preserve page image metadata."""
    data = b"".join(
        [
            _new_class_tag("CBackgroundImage", schema=10),
            _background_image_payload_bytes(),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CBackgroundImage": 10,
            "CEntity": 3,
            "CDib": 3,
        },
    )

    assert isinstance(preview, PageBackgroundImage)
    assert preview.path == "match-photo.png"
    assert preview.reference_state == 1
    assert preview.image_data == b"PNG"
    assert preview.width == 640
    assert preview.height == 480
    assert preview.file_size == 12_345
    assert preview.timestamp == 1_700_000_000
    assert preview.visible is True
    assert preview.opacity == 0.75
    assert [point.to_tuple() for point in preview.grip_points] == [
        (1.0, 2.0, 3.0),
        (4.0, 5.0, 6.0),
    ]
    assert preview.principal_point_delta.to_tuple() == (0.0, 0.0, 1.0)
    assert preview.radial_distortion_k1 == -2.5
    assert preview.image_source == 0x12
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_face_texture_coords() -> None:
    """Dispatch CFaceTextureCoords v4 without losing archive alignment."""
    data = b"".join(
        [
            _new_class_tag("CFaceTextureCoords", schema=4),
            _face_texture_coords_payload_bytes(),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CFaceTextureCoords": 4,
        },
    )

    flags, front_uv, back_uv, front_flags, back_flags = preview
    assert flags == 0
    assert front_uv.transform == list(_identity_matrix3_values())
    assert front_uv.origin == (0.0, 0.0, 1.0)
    assert front_uv.projection_direction is None
    assert back_uv is not None
    assert back_uv.transform == list(_identity_matrix3_values())
    assert back_uv.origin == (0.0, 0.0, -1.0)
    assert back_uv.projection_direction == (0.0, 0.0, -1.0)
    assert len(front_uv.pins) == 1
    assert front_uv.pins[0].texture_position == Vector2D(1.0, 2.0)
    assert front_uv.pins[0].model_position == Vector2D(3.0, 4.0)
    assert back_uv.pins == []
    assert front_flags == 1
    assert back_flags == 2
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_relationship() -> None:
    """Dispatch CRelationship entity links from component relationship managers."""
    data = b"".join(
        [
            _new_class_tag("CRelationship", schema=0),
            b"\x00\x00",
            _object_ref_tag(42),
            _object_ref_tag(84),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CRelationship": 0,
        },
    )

    assert isinstance(preview, tuple)
    assert preview[0].index == 42
    assert preview[1].index == 84
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_relationship_map() -> None:
    """Dispatch CRelationshipMap v0 with contained relationship objects."""
    data = b"".join(
        [
            _new_class_tag("CRelationshipMap", schema=0),
            struct.pack("<I", 1),
            _new_class_tag("CRelationship", schema=0),
            b"\x00\x00",
            _object_ref_tag(42),
            _object_ref_tag(84),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CRelationship": 0,
            "CRelationshipMap": 0,
        },
    )

    assert isinstance(preview, tuple)
    assert len(preview) == 1
    assert preview[0][0].index == 42
    assert preview[0][1].index == 84
    assert session.tell() == len(data)
