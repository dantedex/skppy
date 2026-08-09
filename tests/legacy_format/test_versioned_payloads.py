# SPDX-License-Identifier: MIT
"""Version-gated payload layouts shared by pre-ZIP SketchUp files."""

from __future__ import annotations

import io
import struct

import pytest

from skppy.data_structure.entities import Curve
from skppy.parser_legacy.base_payloads import read_entity_header_body
from skppy.parser_legacy.binary import ArchiveObjectTag, LegacyArchiveReader
from skppy.parser_legacy.component_payloads import read_component_instance_body
from skppy.parser_legacy.geometry_payloads import (
    read_arc_curve_payload,
    read_guide_line_payload,
    read_section_plane_payload,
)
from skppy.parser_legacy.rendering_options import read_rendering_options_payload
from skppy.parser_legacy.metadata_payloads import read_font_payload
from skppy.parser_legacy.metadata_payloads import read_text_style_fields
from skppy.parser_legacy.session import LegacyArchiveSession
from skppy.parser_legacy.object_dispatch import read_supported_object

from ._fixtures import (
    _arc3d_preview_payload_bytes,
    _component_instance_transform_values,
    _font_preview_payload_bytes,
    _legacy_string,
    _new_class_tag,
    _rendering_options_bytes,
)


def test_entity_v5_decodes_sparse_persistent_id() -> None:
    """CEntity v5 stores only the populated bytes of its 64-bit ID."""
    reader = LegacyArchiveReader(io.BytesIO(b"\x89\x12\x34\x56"))

    header = read_entity_header_body(
        reader,
        class_version=5,
        read_reference=lambda: ArchiveObjectTag("null", 0, 0),
    )

    assert header.persistent_id == 0x5600000034000012
    assert reader.tell() == 4


@pytest.mark.parametrize("class_version", [1, 2, 3])
def test_arc_curve_versions_share_arc3d_layout(class_version: int) -> None:
    """ArcCurve schemas 1-3 use the same observed Arc3d body."""
    data = _arc3d_preview_payload_bytes()
    reader = LegacyArchiveReader(io.BytesIO(data))

    arc = read_arc_curve_payload(
        reader,
        class_version=class_version,
        curve=Curve(id=0, edge_ids=[1, 2]),
    )

    assert arc.center == (1.0, 2.0, 3.0)
    assert arc.radius == 1.0
    assert reader.tell() == len(data)


@pytest.mark.parametrize("class_version", [5, 6])
def test_component_instance_newer_versions_read_serialized_guid(
    class_version: int,
) -> None:
    """ComponentInstance schemas 5-6 append a stable 16-byte GUID."""
    guid = bytes(range(16))
    data = b"".join(
        [
            struct.pack("<13d", *_component_instance_transform_values()),
            _legacy_string("Instance"),
            guid,
        ]
    )
    reader = LegacyArchiveReader(io.BytesIO(data))

    instance = read_component_instance_body(
        reader,
        class_version=class_version,
        definition_id=7,
        material_id=3,
    )

    assert instance.guid == guid
    assert instance.name == "Instance"
    assert instance.definition_id == 7
    assert reader.tell() == len(data)


def test_font_reads_versioned_entity_header_before_payload() -> None:
    """A CSkFont in SketchUp 2017 includes the CEntity v5 sparse ID."""
    data = b"".join(
        [
            _new_class_tag("CSkFont", schema=1),
            b"\x00\x00",
            b"\x01\x2a",
            _font_preview_payload_bytes("Arial"),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    font = read_supported_object(session, {"CEntity": 5, "CSkFont": 1})

    assert font.face_name == "Arial"
    assert session.tell() == len(data)


def test_font_v0_ends_after_point_size() -> None:
    """The font world-size fields were introduced by CSkFont schema 1."""
    data = b"".join([_legacy_string("Arial"), b"\x01\x00", struct.pack("<I", 12)])
    reader = LegacyArchiveReader(io.BytesIO(data))

    font = read_font_payload(reader, 0)

    assert font.face_name == "Arial"
    assert font.bold is True
    assert font.use_world_size is False
    assert reader.tell() == len(data)


def test_text_style_v4_reuses_primary_color() -> None:
    """CTextStyle v4 has no separate screen color or screen-font reference."""
    color = bytes((10, 20, 30, 255))
    data = b"".join(
        [
            struct.pack("<II", 1, 2),
            b"\x01",
            struct.pack("<I", 3),
            b"\x00",
            color,
        ]
    )
    reader = LegacyArchiveReader(io.BytesIO(data))

    fields = read_text_style_fields(reader, class_version=4)

    assert fields["screen_color"] == fields["color"]
    assert reader.tell() == len(data)


def test_su3_guide_line_uses_ray_body_despite_schema_one() -> None:
    """SU3 advertises CConstructionLine v1 but writes only the old ray body."""
    data = struct.pack("<6d", 1.0, 2.0, 3.0, 0.0, 1.0, 0.0)
    reader = LegacyArchiveReader(io.BytesIO(data))

    guide = read_guide_line_payload(
        reader,
        class_version=1,
        file_version="3.0.1",
    )

    assert (guide.point.x, guide.point.y, guide.point.z) == (1.0, 2.0, 3.0)
    assert (guide.direction.x, guide.direction.y, guide.direction.z) == (
        0.0,
        1.0,
        0.0,
    )
    assert guide.stipple_pattern == 0
    assert reader.tell() == len(data)


def test_downsaved_section_plane_omits_schema_three_names() -> None:
    """Later runtime tags retain schema 3 while pre-SU2018 bodies omit names."""
    data = struct.pack("<4d", 0.0, 0.0, 1.0, 0.0)
    reader = LegacyArchiveReader(io.BytesIO(data))

    plane = read_section_plane_payload(
        reader,
        class_version=3,
        file_version="17.0.1",
    )

    assert plane.plane == (0.0, 0.0, 1.0, 0.0)
    assert plane.name == ""
    assert plane.symbol == ""
    assert reader.tell() == len(data)


@pytest.mark.parametrize("class_version", [22, 25, 28, 32, 35, 36, 37, 38, 39])
def test_rendering_options_support_sdk_schema_range(class_version: int) -> None:
    """Decode rendering-option layouts emitted from SU3 through SU2020."""
    data = _rendering_options_bytes(class_version)[2:]
    reader = LegacyArchiveReader(io.BytesIO(data))

    options = read_rendering_options_payload(reader, class_version)

    assert options.render_mode == 2
    assert options.edge_display_mode == 1
    assert options.model_transparency is True
    assert options.material_transparency is False
    assert options.texture is False
    assert options.face_color_mode == 0
    assert options.background_color == 0xFFFFFFFF
    assert options.foreground_color == 0xFF808080
    assert options.highlight_color == 0xFF000000
    assert options.construction_color == 0xFF404040
    assert options.face_front_color == 0xFFE1E1C8
    assert options.face_back_color == 0xFF8080C8
    assert options.edge_color_mode == 8
    assert options.line_extension == 3
    assert options.silhouette_width == 4
    assert options.inactive_fade == 0.75
    assert options.instance_fade == 0.5
    assert options.draw_ground is True
    assert options.display_section_planes is False
    assert options.display_section_cuts is True
    assert options.draw_soft_edges is True
    assert options.soft_edge_limit == 0.33
    assert options.draw_smooth_edges is False
    if class_version >= 29:
        assert options.fog_color == 0xFFFF0000
        assert options.fog_start_dist == 0.25
        assert options.fog_end_dist == 0.125
    if class_version >= 26:
        assert options.depth_que_width == 5
        assert options.line_end_width == 6
    if class_version >= 27:
        assert options.locked_color == 0x04010203
    if class_version >= 35:
        assert options.xray_opacity == 0.66
    if class_version >= 36:
        assert options.draw_back_edges is True
        assert options.photomatch_background_opacity == 0.99
        assert options.photomatch_overlay_opacity == 1.2
    assert reader.tell() == len(data)
