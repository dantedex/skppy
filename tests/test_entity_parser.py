# SPDX-License-Identifier: MIT
"""Focused tests for modern entity payload normalization."""

import struct

from skppy.data_structure.primitives import Vector2D
from skppy.parser.entities import (
    _read_face_uv_projection,
    _normalize_modern_edge_flags,
    _parse_guide_lines,
    _parse_guide_points,
    _parse_dimensions,
)

# Expected public flags are stated locally so a production constant change does
# not silently change the assertion: hidden=0x01, soft=0x02, smooth=0x04.
EDGE_FLAG_HIDDEN = 0x01
EDGE_FLAG_SOFT = 0x02
EDGE_FLAG_SMOOTH = 0x04


def _record(tag: int, payload: bytes) -> bytes:
    return struct.pack("<HI", tag, len(payload)) + payload


def test_modern_edge_flags_ignore_generic_drawing_element_bits() -> None:
    """The baseline modern entity flags must still produce a flat edge."""
    assert _normalize_modern_edge_flags(0x06) == 0


def test_modern_edge_flags_map_each_edge_property_independently() -> None:
    """Normalize hidden, soft, and smooth bits to the shared public layout."""
    assert _normalize_modern_edge_flags(0x07) == EDGE_FLAG_HIDDEN
    assert _normalize_modern_edge_flags(0x0E) == EDGE_FLAG_SOFT
    assert _normalize_modern_edge_flags(0x16) == EDGE_FLAG_SMOOTH
    assert _normalize_modern_edge_flags(0x1F) == (EDGE_FLAG_HIDDEN | EDGE_FLAG_SOFT | EDGE_FLAG_SMOOTH)


def test_modern_face_projection_decodes_texture_control_points() -> None:
    # 0x2710-0x271A are the projection pair, side, transform, and pin records.
    pin = _record(
        0x2718,
        b"".join(
            (
                _record(
                    0x2719,
                    struct.pack("<2d", 8.0, 6.0),
                ),
                _record(
                    0x271A,
                    struct.pack("<2d", 1.0, 2.0),
                ),
            )
        ),
    )
    projection_payload = b"".join(
        (
            _record(0x2714, b"\x01"),
            _record(
                0x2715,
                struct.pack("<9d", 1, 0, 0, 0, 1, 0, 0, 0, 1),
            ),
            _record(0x2716, struct.pack("<3d", 0, 0, 0)),
            _record(0x2717, pin),
        )
    )
    entity_base = _record(
        0x05DC,
        _record(
            0x05DD,
            _record(
                0x36B1,
                _record(
                    0x36B2,
                    _record(
                        0x2710,
                        _record(
                            0x2711,
                            _record(0x2713, projection_payload),
                        ),
                    ),
                ),
            ),
        ),
    )

    projection = _read_face_uv_projection(entity_base)

    assert projection is not None
    assert len(projection.pins) == 1
    assert projection.pins[0].texture_position == Vector2D(8.0, 6.0)
    assert projection.pins[0].model_position == Vector2D(1.0, 2.0)


def test_modern_guide_point_maps_optional_reference_position() -> None:
    """Decode the point tags without the historical point/line name swap."""
    # 0x4268 is construction geometry; 0x426C-0x426F describe a guide point.
    entity_id = _record(
        0x4268,
        _record(0x05DC, _record(0x05DE, b"\x2a")),
    )
    payload = _record(
        0x426C,
        b"".join(
            (
                entity_id,
                _record(0x426D, struct.pack("<3d", 1, 2, 3)),
                _record(
                    0x426E,
                    struct.pack("<3d", 4, 5, 6),
                ),
                _record(0x426F, b"\x01"),
            )
        ),
    )

    point = _parse_guide_points(payload)[0]

    assert point.id == 42
    assert point.position == (1.0, 2.0, 3.0)
    assert point.reference_point == (4.0, 5.0, 6.0)


def test_modern_guide_line_maps_stipple_pattern() -> None:
    """Decode the CLine3d field and its named 16-bit stipple pattern."""
    payload = _record(
        0x4269,
        b"".join(
            (
                _record(0x4268, b""),
                _record(
                    0x426A,
                    struct.pack("<8d", 1, 2, 3, 0, 0, 1, -10, 10),
                ),
                _record(0x426B, b"\xaa\xaa"),
            )
        ),
    )

    line = _parse_guide_lines(payload)[0]

    assert line.point == (1.0, 2.0, 3.0)
    assert line.direction == (0.0, 0.0, 1.0)
    assert line.stipple_pattern == 0xAAAA


def test_modern_sparse_guides_keep_wire_fallback_types() -> None:
    """Do not inherit authored-object directions for missing wire geometry."""
    # 0x426C and 0x4269 are empty guide-point and guide-line records.
    point = _parse_guide_points(_record(0x426C, b""))[0]
    line = _parse_guide_lines(_record(0x4269, b""))[0]

    assert point.position == (0.0, 0.0, 0.0)
    assert line.point == (0.0, 0.0, 0.0)
    assert line.direction == (0.0, 0.0, 0.0)


def test_modern_dimension_maps_shared_annotation_fields() -> None:
    """Expose modern dimension records through the version-neutral model."""
    # 0x59D8 is the annotation base and 0x5BCC-0x5BD4 are linear-dimension fields.
    entity_base = _record(
        0x07D0,
        b"".join(
            (
                _record(0x05DC, _record(0x05DE, b"\x2a")),
                _record(0x07D1, b"\x07"),
                _record(0x07D3, b"\x01"),
            )
        ),
    )
    common = _record(
        0x59D8,
        b"".join(
            (
                _record(0x59D9, b"Length"),
                _record(0x59DA, b"\x03"),
                _record(0x59DB, b"\x01"),
                _record(0x59DC, b"\x04"),
            )
        ),
    )

    def anchor(tag: int, point: tuple[float, float, float]) -> bytes:
        return _record(
            tag,
            _record(
                0x5208,
                _record(0x5209, b"\x01") + _record(0x520A, struct.pack("<3d", *point)),
            ),
        )

    record = _record(
        0x5BCC,
        b"".join(
            (
                entity_base,
                common,
                anchor(0x5BCD, (1.0, 2.0, 3.0)),
                anchor(0x5BCE, (4.0, 5.0, 6.0)),
                _record(0x5BCF, struct.pack("<3d", 0, 0, 1)),
                _record(0x5BD0, struct.pack("<3d", 1, 0, 0)),
                _record(0x5BD1, struct.pack("<I", 2)),
                _record(0x5BD3, struct.pack("<d", 2.5)),
                _record(0x5BD2, struct.pack("<d", 7.5)),
                _record(0x5BD4, struct.pack("<I", 3)),
            )
        ),
    )

    dimension = _parse_dimensions(record)[0]

    assert dimension.id == 42
    assert dimension.text == "Length"
    assert dimension.font_id == 3
    assert dimension.is_3d_text is True
    assert dimension.arrow_type == 4
    assert dimension.drawing.material_id == 7
    assert dimension.drawing.hidden is True
    assert dimension.start.position.to_tuple() == (1.0, 2.0, 3.0)
    assert dimension.end.position.to_tuple() == (4.0, 5.0, 6.0)
    assert dimension.direction.to_tuple() == (0.0, 0.0, 1.0)
    assert dimension.render_direction.to_tuple() == (1.0, 0.0, 0.0)
    assert (dimension.mode, dimension.offset, dimension.line_position) == (2, 2.5, 7.5)
    assert dimension.alignment == 3
