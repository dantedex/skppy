# SPDX-License-Identifier: MIT
"""Version guards, scalar branches, and payload boundary contracts."""

from __future__ import annotations

import io
import struct

import pytest

from skppy.data_structure.entities import ComponentInstance, Curve
from skppy.parser_legacy.annotation_payloads import read_dimension_radial_fields
from skppy.parser_legacy.attribute_builder import attribute_dictionaries_by_owner_id
from skppy.parser_legacy.attribute_payloads import _restore_entry_flags, attribute_dictionary_entry
from skppy.parser_legacy.base_payloads import (
    read_component_behavior_body,
    read_entity_header_body,
    read_root_model_prefix,
)
from skppy.parser_legacy.binary import (
    ArchiveIndexTable,
    ArchiveObjectTag,
    LegacyArchiveBuffer,
    LegacyArchiveReader,
)
from skppy.parser_legacy.component_payloads import (
    component_instance_as_group,
    component_instance_as_image,
    read_component_instance_body,
    read_definition_list_payload,
    read_root_component,
)
from skppy.parser_legacy.envelope import read_legacy_envelope
from skppy.parser_legacy.errors import UnsupportedLegacySchemaError
from skppy.parser_legacy.geometry_payloads import (
    read_arc_curve_payload,
    read_curve_payload,
    read_guide_line_payload,
    read_guide_point_payload,
    read_polyline_points,
    read_section_plane_payload,
)
from skppy.parser_legacy.options_payloads import _option_value_to_string
from skppy.parser_legacy.relationship_payloads import read_relationship_map_body
from skppy.parser_legacy.schema import SketchUpFormatVersion
from skppy.parser_legacy.uv_payloads import (
    _read_texture_push_pins,
    read_face_texture_coords_body,
)
from skppy.parser_legacy.visual_payloads import (
    read_background_image_fields,
    read_image_reference_prefix,
    read_watermark_fields,
    read_watermark_manager_body,
)

from ._fixtures import _legacy_string


def _reader(data: bytes = b"") -> LegacyArchiveReader:
    return LegacyArchiveReader(io.BytesIO(data))


def test_archive_buffer_supports_full_seek_protocol_and_u64_reads():
    stream = LegacyArchiveBuffer(b"abcdef")
    assert stream.readable() and stream.seekable()
    assert stream.read(2) == b"ab"
    assert stream.seek(1, io.SEEK_CUR) == 3
    assert stream.seek(-1, io.SEEK_END) == 5
    with pytest.raises(ValueError, match="Invalid seek mode"):
        stream.seek(0, 99)
    with pytest.raises(ValueError, match="Negative seek position"):
        stream.seek(-1)
    assert _reader(struct.pack("<Q", 0x123456789ABCDEF0)).read_u64() == 0x123456789ABCDEF0


def test_archive_index_ignores_non_registering_tags():
    table = ArchiveIndexTable()
    assert table.register_new_object_tag(ArchiveObjectTag("null", 0)) is None
    assert table.register_new_object_tag(ArchiveObjectTag("object_ref", 1, index=1)) is None


def test_root_entity_and_behavior_version_branches():
    prefix = b"".join(
        (
            struct.pack("<IIIQ", 1, 2, 3, 0x1234),
            b"\x00\x00",
            b"\x01",
        )
    )
    state = read_root_model_prefix(io.BytesIO(prefix), 26)
    assert state.next_persistent_id == 0x1234

    legacy = read_entity_header_body(_reader(struct.pack("<I", 0xAA)), class_version=1, read_reference=lambda: None)
    assert legacy.legacy_flags_u32 == 0xAA

    persistent = read_entity_header_body(
        _reader(struct.pack("<Q", 0x55)),
        class_version=4,
        read_reference=lambda: ArchiveObjectTag("null", 0),
    )
    assert persistent.persistent_id == 0x55

    header = read_entity_header_body(_reader(), class_version=2, read_reference=lambda: ArchiveObjectTag("null", 0))
    behavior = read_component_behavior_body(
        _reader(b"\x01" + struct.pack("<I", 7)),
        class_version=2,
        object_tag=None,
        payload_start_offset=0,
        entity_header=header,
    )
    assert behavior.is_2d and behavior.cuts_opening and behavior.snap_to == 7


def test_root_component_disambiguates_optional_leading_value():
    assert read_root_component(io.BytesIO(struct.pack("<II", 0, 4)))[1:] == (4, 8, 0)
    stream = io.BytesIO(struct.pack("<II", 0, 1_000_000))
    result = read_root_component(stream)
    assert result == (0, 0, 4, None)


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (
            lambda: read_dimension_radial_fields(_reader(), class_version=1, target_is_null=False),
            "CDimensionRadial",
        ),
        (
            lambda: read_definition_list_payload(None, class_version=1, resolve=lambda _handle: None),
            "CDefinitionList",
        ),
        (
            lambda: read_component_instance_body(_reader(), class_version=2, definition_id=0, material_id=None),
            "CComponentInstance",
        ),
        (
            lambda: component_instance_as_group(ComponentInstance(), class_version=2),
            "CGroup",
        ),
        (
            lambda: component_instance_as_image(ComponentInstance(), class_version=2),
            "CImage",
        ),
        (lambda: read_curve_payload(_reader(), class_version=2), "CCurve"),
        (
            lambda: read_arc_curve_payload(_reader(), class_version=0, curve=Curve()),
            "CArcCurve",
        ),
        (
            lambda: read_guide_point_payload(_reader(), class_version=1),
            "CConstructionPoint",
        ),
        (
            lambda: read_guide_line_payload(_reader(), class_version=3),
            "CConstructionLine",
        ),
        (
            lambda: read_section_plane_payload(_reader(), class_version=4),
            "CSectionPlane",
        ),
        (lambda: read_polyline_points(_reader(), class_version=2), "CPolyline3d"),
        (
            lambda: read_relationship_map_body(_reader(), class_version=1, read_object=lambda: None),
            "CRelationshipMap",
        ),
        (lambda: read_face_texture_coords_body(_reader(), 5), "CFaceTextureCoords"),
        (
            lambda: read_background_image_fields(_reader(), class_version=9),
            "CBackgroundImage",
        ),
        (lambda: read_watermark_fields(_reader(), class_version=0), "CWatermark"),
        (
            lambda: read_watermark_manager_body(_reader(), class_version=1, read_object=lambda: None),
            "CWatermarkManager",
        ),
        (
            lambda: read_image_reference_prefix(_reader(), class_version=2),
            "ImageReference",
        ),
    ],
)
def test_payload_readers_reject_unmapped_versions(call, message):
    with pytest.raises(NotImplementedError, match=message):
        call()


def test_texture_projection_flags_and_pin_limit():
    values = [0, *range(9), *range(3), *range(9), *range(3)]
    payload = struct.pack("<I", values[0]) + struct.pack("<24d", *values[1:])
    payload += struct.pack("<IIIII", 0, 0, 2, 2, 0)
    _, front, back, front_flags, back_flags = read_face_texture_coords_body(_reader(payload), 4)
    assert front.projection_direction == front.origin
    assert back is not None and back.projection_direction == back.origin
    assert (front_flags, back_flags) == (2, 2)

    with pytest.raises(ValueError, match="Unreasonable"):
        _read_texture_push_pins(_reader(struct.pack("<I", 1_000_001)))


@pytest.mark.parametrize(
    ("value", "value_type", "field", "expected"),
    [
        (3, 0, "int_value", 3),
        (1.5, 1, "float_value", 1.5),
        ("value", 3, "string_value", "value"),
        ((1, 2), 4, "nested_payload", b"\x01\x02"),
        ((1.5, 2.5), 4, "nested_payload", b"(1.5, 2.5)"),
    ],
)
def test_attribute_entries_cover_each_native_value(value, value_type, field, expected):
    entry = attribute_dictionary_entry("key", value)
    assert entry.value_type == value_type
    assert getattr(entry, field) == expected


def test_attribute_entry_flag_extensions_are_restored_and_hidden():
    value = attribute_dictionary_entry("value", "text")
    flag = attribute_dictionary_entry("__skppy_flags__:value", 7)

    assert _restore_entry_flags([value, flag]) == [value]
    assert value.flags == 7


def test_attribute_owner_builder_rejects_incomplete_mappings():
    tag = ArchiveObjectTag("object_ref", 1, index=1)
    good_dictionary = attribute_dictionary_entry("key", True)
    assert (
        attribute_dictionaries_by_owner_id(((1, 2),), (), {}, objects_by_archive_index={2: (tag, (), (), 0, 0)}) == {}
    )
    assert attribute_dictionaries_by_owner_id(((1, 2),), (), {1: 10}, objects_by_archive_index={2: "bad"}) == {}
    assert (
        attribute_dictionaries_by_owner_id(((1, 2),), (), {1: 10}, objects_by_archive_index={2: (tag, (), [], 0, 0)})
        == {}
    )
    assert (
        attribute_dictionaries_by_owner_id(
            ((1, 2),),
            (),
            {1: 10},
            objects_by_archive_index={2: (tag, (), (good_dictionary,), 0, 0)},
        )
        == {}
    )


def test_option_none_and_schema_error_messages():
    assert _option_value_to_string(None) == ""
    error = UnsupportedLegacySchemaError("CEdge", 9, "8.0", offset=0x20, object_index=4)
    assert "object 4" in str(error) and "offset 0x20" in str(error)
    with pytest.raises(ValueError, match="Unsupported SketchUp version string"):
        SketchUpFormatVersion.parse("not-a-version")


def test_legacy_envelope_rejects_zip_versions_and_bad_version_maps():
    header = _legacy_string("SketchUp Model") + _legacy_string("{21.0.0}")
    with pytest.raises(ValueError, match="not a pre-ZIP"):
        read_legacy_envelope(io.BytesIO(header))

    prefix = b"".join(
        (
            _legacy_string("SketchUp Model"),
            _legacy_string("{8.0.0}"),
            bytes(16),
            _legacy_string("model.skp"),
            struct.pack("<I", 0),
        )
    )
    with pytest.raises(ValueError, match="Unexpected CVersionMap magic"):
        read_legacy_envelope(io.BytesIO(prefix + b"bad!"))
    with pytest.raises(ValueError, match="version map block name"):
        read_legacy_envelope(io.BytesIO(prefix + b"\xff\xff\x00\x00\x03\x00bad"))
