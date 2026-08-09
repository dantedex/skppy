# SPDX-License-Identifier: MIT
"""Literal modern entity fixtures for defensive and annotation branches."""

from __future__ import annotations

import struct

import pytest

import skppy.parser.entities as entity_parser
from skppy.data_structure.annotations import LinearDimension
from skppy.writer.tlv import encode_record


class Tag:
    """Observed wire tags kept independent of the production tag enum."""

    UNKNOWN = 0xFFFF
    ID_WRAPPER = 0x05DC
    ID_EXT_PAYLOAD = 0x05DD
    ID_VALUE = 0x05DE
    ENTITY_BASE = 0x07D0
    ENTITY_MATERIAL_REF = 0x07D1
    ENTITY_LAYER_REF = 0x07D2
    ENTITY_FLAGS = 0x07D3
    VERTEX_RECORD = 0x09C4
    EDGE_RECORD = 0x0BB8
    FACE_RECORD = 0x0DAC
    EDGE_USE = 0x0FA0
    LOOP_RECORD = 0x1194
    INSTANCE_RECORD = 0x1964
    GROUP_RECORD = 0x1D4C
    IMAGE_RECORD = 0x1F40
    TEX_PROJ_PAIR = 0x2710
    TEX_PROJ_FRONT = 0x2711
    TEX_PROJ_PAYLOAD = 0x2713
    TEX_PROJ_ENABLED = 0x2714
    TEX_PROJ_TRANSFORM = 0x2715
    TEX_PROJ_ORIGIN = 0x2716
    TEX_PROJ_PINS = 0x2717
    TEX_PROJ_PIN = 0x2718
    TEX_PROJ_PIN_TEXTURE_POSITION = 0x2719
    TEX_PROJ_PIN_MODEL_POSITION = 0x271A
    ATTR_DICTS_ROOT = 0x36B1
    ATTR_DICT_RECORD = 0x36B2
    GUIDE_LINE_RECORD = 0x4269
    GUIDE_POINT_RECORD = 0x426C
    SECTION_PLANE_RECORD = 0x445C
    CURVE_RECORD = 0x4A38
    CURVE_EDGE_COUNT = 0x4A39
    CURVE_FIRST_EDGE_ID = 0x4A3B
    CURVE_LAST_EDGE_ID = 0x4A3C
    ARC_CURVE_RECORD = 0x4C2C
    POINT_REFERENCE = 0x5208
    DIMENSION_ANCHOR_ENABLED = 0x5209
    DIMENSION_ANCHOR_POINT = 0x520A
    DIMENSION_ANCHOR_STYLE_A = 0x520B
    DIMENSION_ANCHOR_STYLE_B = 0x520C
    DIMENSION_ANCHOR_STYLE_WRAPPER = 0x53FC
    DIMENSION_ANCHOR_STYLE_ENTITY = 0x53FD
    DIMENSION_ANCHOR_STYLE_VALUE = 0x53FE
    TEXT_RECORD = 0x55F0
    TEXT_VALUE = 0x55F1
    TEXT_SCREEN_X = 0x55F2
    TEXT_SCREEN_Y = 0x55F3
    TEXT_ANCHOR = 0x55F4
    TEXT_LEADER_VECTOR = 0x55F5
    TEXT_ANCHOR_IN_FRONT = 0x55F6
    TEXT_VIEW_DIRECTION = 0x55F7
    TEXT_HIDE_OUT_OF_PLANE = 0x55F8
    TEXT_FONT_REF = 0x55F9
    TEXT_LINE_WEIGHT = 0x55FA
    TEXT_LEADER_TYPE = 0x55FB
    TEXT_DISPLAY_LEADER = 0x55FC
    TEXT_ARROW_TYPE = 0x55FD
    TEXT_HIDDEN_LEADER_DIRECTION = 0x55FE
    DIMENSION_BASE = 0x59D8
    DIMENSION_TEXT = 0x59D9
    DIMENSION_FONT_REF = 0x59DA
    DIMENSION_3D_TEXT = 0x59DB
    DIMENSION_ARROW_TYPE = 0x59DC
    DIMENSION_RECORD = 0x5BCC
    DIMENSION_ANCHOR_A = 0x5BCD
    DIMENSION_ANCHOR_B = 0x5BCE
    DIMENSION_DIRECTION = 0x5BCF
    DIMENSION_RENDER_DIR = 0x5BD0
    DIMENSION_MODE = 0x5BD1
    DIMENSION_LINE_POS = 0x5BD2
    DIMENSION_OFFSET = 0x5BD3
    DIMENSION_ALIGNMENT = 0x5BD4
    RADIAL_DIMENSION_RECORD = 0x5DC0
    RADIAL_DIMENSION_TARGET_REF = 0x5DC1
    RADIAL_DIMENSION_ARC = 0x5DC2
    RADIAL_DIMENSION_PARAMETER = 0x5DC3
    RADIAL_DIMENSION_RADIUS_RATIO = 0x5DC4
    RADIAL_DIMENSION_IS_DIAMETER = 0x5DC5


def _record(tag: int, payload: bytes = b"") -> bytes:
    return encode_record(tag, payload)


def _entity_base(entity_id: int = 7) -> bytes:
    return b"".join(
        (
            _record(Tag.ID_WRAPPER, _record(Tag.ID_VALUE, bytes((entity_id,)))),
            _record(Tag.ENTITY_MATERIAL_REF, b"\x09"),
            _record(Tag.ENTITY_LAYER_REF, b"\x0a"),
            _record(Tag.ENTITY_FLAGS, b"\x07"),
        )
    )


def _uv_chain(inner: bytes) -> bytes:
    return _record(
        Tag.ID_WRAPPER,
        _record(
            Tag.ID_EXT_PAYLOAD,
            _record(
                Tag.ATTR_DICTS_ROOT,
                _record(
                    Tag.ATTR_DICT_RECORD,
                    _record(Tag.TEX_PROJ_PAIR, inner),
                ),
            ),
        ),
    )


def test_uv_projection_rejects_each_incomplete_wrapper_level():
    payloads = [
        b"",
        _record(Tag.ID_WRAPPER, _record(Tag.UNKNOWN)),
        _record(Tag.ID_WRAPPER, _record(Tag.ID_EXT_PAYLOAD, _record(Tag.UNKNOWN))),
        _record(
            Tag.ID_WRAPPER,
            _record(
                Tag.ID_EXT_PAYLOAD,
                _record(Tag.ATTR_DICTS_ROOT, _record(Tag.UNKNOWN)),
            ),
        ),
        _record(
            Tag.ID_WRAPPER,
            _record(
                Tag.ID_EXT_PAYLOAD,
                _record(
                    Tag.ATTR_DICTS_ROOT,
                    _record(Tag.ATTR_DICT_RECORD, _record(Tag.UNKNOWN)),
                ),
            ),
        ),
    ]
    assert all(entity_parser._read_face_uv_projections(payload) == (None, None) for payload in payloads)


def test_uv_projection_rejects_incomplete_side_and_pin_records():
    sides = [
        _record(Tag.TEX_PROJ_FRONT, _record(Tag.UNKNOWN)),
        _record(
            Tag.TEX_PROJ_FRONT,
            _record(Tag.TEX_PROJ_PAYLOAD, _record(Tag.TEX_PROJ_ENABLED, b"\x00")),
        ),
        _record(
            Tag.TEX_PROJ_FRONT,
            _record(
                Tag.TEX_PROJ_PAYLOAD,
                _record(Tag.TEX_PROJ_ENABLED, b"\x01") + _record(Tag.TEX_PROJ_TRANSFORM, b"short"),
            ),
        ),
        _record(
            Tag.TEX_PROJ_FRONT,
            _record(
                Tag.TEX_PROJ_PAYLOAD,
                _record(Tag.TEX_PROJ_ENABLED, b"\x01")
                + _record(Tag.TEX_PROJ_TRANSFORM, struct.pack("<9d", *range(9)))
                + _record(Tag.TEX_PROJ_ORIGIN, b"short"),
            ),
        ),
    ]
    assert all(entity_parser._read_face_uv_projections(_uv_chain(side))[0] is None for side in sides)

    projection_payload = b"".join(
        (
            _record(Tag.TEX_PROJ_ENABLED, b"\x01"),
            _record(Tag.TEX_PROJ_TRANSFORM, struct.pack("<9d", *range(9))),
            _record(Tag.TEX_PROJ_ORIGIN, struct.pack("<3d", 0.0, 0.0, 0.0)),
            _record(
                Tag.TEX_PROJ_PINS,
                _record(Tag.UNKNOWN)
                + _record(
                    Tag.TEX_PROJ_PIN,
                    _record(Tag.TEX_PROJ_PIN_TEXTURE_POSITION, b"short"),
                ),
            ),
        )
    )
    side = _record(Tag.TEX_PROJ_FRONT, _record(Tag.TEX_PROJ_PAYLOAD, projection_payload))
    projection = entity_parser._read_face_uv_projections(_uv_chain(side))[0]
    assert projection is not None and projection.pins == []


@pytest.mark.parametrize(
    "parser",
    [
        entity_parser._parse_vertices,
        entity_parser._parse_edges,
        entity_parser._parse_faces,
        entity_parser._parse_loops,
        entity_parser._parse_component_instances,
        entity_parser._parse_groups,
        entity_parser._parse_images,
        entity_parser._parse_curves,
        entity_parser._parse_arc_curves,
        entity_parser._parse_guide_points,
        entity_parser._parse_guide_lines,
        entity_parser._parse_section_planes,
        entity_parser._parse_texts,
        entity_parser._parse_dimensions,
        entity_parser._parse_radial_dimensions,
    ],
)
def test_entity_section_parsers_skip_unrelated_records(parser):
    assert parser(_record(Tag.UNKNOWN)) == []


def test_face_and_loop_helpers_cover_empty_topology_and_unrelated_edge_uses():
    outer, inner = entity_parser._face_loops(_record(Tag.UNKNOWN))
    assert outer.is_outer and outer.edge_uses == [] and inner == []
    loops = entity_parser._parse_loops(
        _record(
            Tag.LOOP_RECORD,
            _record(0x1195, _record(Tag.UNKNOWN)),
        )
    )
    assert loops[0].edge_uses == []


def test_scoped_attribute_scan_skips_unrelated_records():
    assert entity_parser._parse_scoped_attribute_dictionaries({0x1389: _record(Tag.UNKNOWN)}) == {}


def test_arc_curve_accepts_first_and_last_edge_range_without_count():
    curve = b"".join(
        (
            _record(Tag.ID_WRAPPER, _record(Tag.ID_VALUE, b"\x20")),
            _record(Tag.CURVE_FIRST_EDGE_ID, b"\x05"),
            _record(Tag.CURVE_LAST_EDGE_ID, b"\x07"),
        )
    )
    arcs = entity_parser._parse_arc_curves(_record(Tag.ARC_CURVE_RECORD, _record(Tag.CURVE_RECORD, curve)))
    assert arcs[0].edge_ids == [5, 6, 7]


def test_width_prefixed_entity_paths_reject_invalid_and_truncated_data():
    with pytest.raises(ValueError, match="width must be 1-4"):
        entity_parser._read_width_prefixed_ids(b"\x00")
    with pytest.raises(ValueError, match="Truncated entity path"):
        entity_parser._read_width_prefixed_ids(b"\x02\x01")


def _anchor() -> bytes:
    style_a = _record(
        Tag.DIMENSION_ANCHOR_STYLE_WRAPPER,
        _record(Tag.DIMENSION_ANCHOR_STYLE_ENTITY, b"\x21")
        + _record(Tag.DIMENSION_ANCHOR_STYLE_VALUE, b"\x01\x05\x02\x06\x00"),
    )
    return _record(
        Tag.POINT_REFERENCE,
        b"".join(
            (
                _record(Tag.DIMENSION_ANCHOR_ENABLED, b"\x02"),
                _record(Tag.DIMENSION_ANCHOR_POINT, struct.pack("<3d", 1.0, 2.0, 3.0)),
                _record(Tag.DIMENSION_ANCHOR_STYLE_A, style_a),
                _record(
                    Tag.DIMENSION_ANCHOR_STYLE_B,
                    _record(Tag.DIMENSION_ANCHOR_STYLE_ENTITY, b"\x22"),
                ),
            )
        ),
    )


def test_text_parser_decodes_complete_annotation_record():
    fields = [
        _record(Tag.ENTITY_BASE, _entity_base()),
        _record(Tag.TEXT_VALUE, b"Label"),
        _record(Tag.TEXT_FONT_REF, b"\x03"),
        _record(Tag.TEXT_LINE_WEIGHT, b"\x04"),
        _record(Tag.TEXT_LEADER_TYPE, b"\x05"),
        _record(Tag.TEXT_ARROW_TYPE, b"\x06"),
        _record(Tag.TEXT_HIDDEN_LEADER_DIRECTION, b"\x07"),
        _record(Tag.TEXT_ANCHOR_IN_FRONT, b"\x01"),
        _record(Tag.TEXT_HIDE_OUT_OF_PLANE, b"\x01"),
        _record(Tag.TEXT_DISPLAY_LEADER, b"\x01"),
        _record(Tag.TEXT_SCREEN_X, struct.pack("<d", 10.0)),
        _record(Tag.TEXT_SCREEN_Y, struct.pack("<d", 20.0)),
        _record(Tag.TEXT_ANCHOR, _anchor()),
        _record(Tag.TEXT_LEADER_VECTOR, struct.pack("<3d", 1.0, 0.0, 0.0)),
        _record(Tag.TEXT_VIEW_DIRECTION, struct.pack("<3d", 0.0, 1.0, 0.0)),
    ]
    text = entity_parser._parse_texts(_record(Tag.TEXT_RECORD, b"".join(fields)))[0]

    assert text.id == 7
    assert text.text == "Label"
    assert text.drawing.material_id == 9
    assert text.drawing.layer_id == 10
    assert text.drawing.hidden and text.drawing.casts_shadows and text.drawing.receives_shadows
    assert (text.screen_position.x, text.screen_position.y) == (10.0, 20.0)
    assert text.anchor.kind == 2
    assert text.anchor.entity_id == 33
    assert text.anchor.instance_path_ids == [5, 6]
    assert text.anchor.secondary_entity_id == 34


def test_disabled_dimension_anchor_and_missing_entity_base_keep_defaults():
    anchor = _record(Tag.POINT_REFERENCE, _record(Tag.DIMENSION_ANCHOR_ENABLED, b"\x00"))
    assert entity_parser._parse_dimension_anchor(anchor).kind == 0
    dimension = LinearDimension()
    entity_parser._apply_dimension_entity_base(dimension, None)
    assert dimension.id == 0


def test_linear_and_radial_dimensions_decode_complete_records():
    common = b"".join(
        (
            _record(Tag.ENTITY_BASE, _entity_base(8)),
            _record(Tag.DIMENSION_TEXT, b"Dimension"),
            _record(Tag.DIMENSION_FONT_REF, b"\x03"),
            _record(Tag.DIMENSION_3D_TEXT, b"\x01"),
            _record(Tag.DIMENSION_ARROW_TYPE, b"\x04"),
        )
    )
    linear_payload = b"".join(
        (
            _record(Tag.DIMENSION_BASE, common),
            _record(Tag.DIMENSION_ANCHOR_A, _anchor()),
            _record(Tag.DIMENSION_ANCHOR_B, _anchor()),
            _record(Tag.DIMENSION_DIRECTION, struct.pack("<3d", 0.0, 0.0, 1.0)),
            _record(Tag.DIMENSION_RENDER_DIR, struct.pack("<3d", 1.0, 0.0, 0.0)),
            _record(Tag.DIMENSION_MODE, b"\x02"),
            _record(Tag.DIMENSION_OFFSET, struct.pack("<d", 3.5)),
            _record(Tag.DIMENSION_LINE_POS, struct.pack("<d", 4.5)),
            _record(Tag.DIMENSION_ALIGNMENT, b"\x03"),
        )
    )
    linear = entity_parser._parse_dimensions(_record(Tag.DIMENSION_RECORD, linear_payload))[0]
    assert (linear.id, linear.text, linear.font_id, linear.mode) == (
        8,
        "Dimension",
        3,
        2,
    )
    assert (linear.offset, linear.line_position, linear.alignment) == (3.5, 4.5, 3)

    arc = struct.pack("<14d", *range(14))
    radial_payload = b"".join(
        (
            _record(Tag.DIMENSION_BASE, common),
            _record(Tag.RADIAL_DIMENSION_TARGET_REF, b"\x2a"),
            _record(Tag.RADIAL_DIMENSION_PARAMETER, struct.pack("<d", 0.25)),
            _record(Tag.RADIAL_DIMENSION_RADIUS_RATIO, struct.pack("<d", 0.5)),
            _record(Tag.RADIAL_DIMENSION_IS_DIAMETER, b"\x01"),
            _record(Tag.RADIAL_DIMENSION_ARC, arc),
        )
    )
    radial = entity_parser._parse_radial_dimensions(_record(Tag.RADIAL_DIMENSION_RECORD, radial_payload))[0]
    assert radial.target_entity_id == 42
    assert radial.parameter == 0.25
    assert radial.radius_ratio == 0.5
    assert radial.is_diameter is True
    assert radial.arc is not None and radial.arc.y_axis is not None
