# SPDX-License-Identifier: MIT
"""Raw-byte checks for modern annotation-style serialization."""

from __future__ import annotations

import struct

import pytest

from skppy.data_structure.model_metadata import DimensionStyle, TextStyle
from skppy.writer.annotation_styles import encode_dimension_style, encode_text_style


def _raw_record(tag: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HI", tag, len(payload)) + payload


def test_text_style_matches_raw_expected_bytes() -> None:
    style = TextStyle(
        font_ref=3,
        screen_font_ref=2,
        arrow_type=3,
        line_weight=2,
        hide_out_of_plane=True,
        leader_type=2,
        display_leader=False,
        color=0xFF0A141E,
        screen_color=0x8028323C,
    )
    expected = _raw_record(
        0x57E4,
        _raw_record(0x57E5, b"\x03")
        + _raw_record(0x57E6, b"\x02")
        + _raw_record(0x57E7, struct.pack("<I", 3))
        + _raw_record(0x57E8, struct.pack("<I", 2))
        + _raw_record(0x57E9, b"\x01")
        + _raw_record(0x57EA, struct.pack("<I", 2))
        + _raw_record(0x57EB, b"\x00")
        + _raw_record(0x57EC, b"\x0a\x14\x1e\xff")
        + _raw_record(0x57ED, b"\x28\x32\x3c\x80"),
    )
    assert encode_text_style(style, 2) == expected


def test_dimension_style_matches_raw_expected_bytes() -> None:
    style = DimensionStyle(
        font_ref=2,
        text_3d=True,
        always_readable=True,
        extension_offset=5,
        extension_overshoot=10,
        line_weight=2,
        arrow_type=3,
        arrow_size=12,
        highlight_non_associative=True,
        highlight_non_associative_color=0xFF00FF00,
        show_radial_diameter_prefix=True,
        hide_out_of_plane=True,
        hide_out_of_plane_value=0.6,
        hide_small=True,
        hide_small_value=10.0,
        color=0xFF404040,
        text_color=0xFF0A141E,
        text_position=1,
    )
    payload = b"".join(
        (
            _raw_record(0x5FB5, b"\x02"),
            _raw_record(0x5FB6, b"\x01"),
            _raw_record(0x5FB7, b"\x01"),
            _raw_record(0x5FB8, struct.pack("<I", 5)),
            _raw_record(0x5FB9, struct.pack("<I", 10)),
            _raw_record(0x5FBA, struct.pack("<I", 2)),
            _raw_record(0x5FBB, struct.pack("<I", 3)),
            _raw_record(0x5FBC, struct.pack("<I", 12)),
            _raw_record(0x5FBD, b"\x01"),
            _raw_record(0x5FBE, b"\x00\xff\x00\xff"),
            _raw_record(0x5FBF, b"\x01"),
            _raw_record(0x5FC0, b"\x01"),
            _raw_record(0x5FC1, struct.pack("<d", 0.6)),
            _raw_record(0x5FC2, b"\x01"),
            _raw_record(0x5FC3, struct.pack("<d", 10.0)),
            _raw_record(0x5FC4, b"\x40\x40\x40\xff"),
            _raw_record(0x5FC5, b"\x0a\x14\x1e\xff"),
            _raw_record(0x5FC6, struct.pack("<I", 1)),
        )
    )
    assert encode_dimension_style(style, 2) == _raw_record(0x5FB4, payload)


def test_annotation_styles_reject_unknown_fonts_and_non_u32_values() -> None:
    with pytest.raises(ValueError, match="does not identify a written font"):
        encode_text_style(TextStyle(font_ref=9, screen_font_ref=2), 2)
    with pytest.raises(ValueError, match="fit in u32"):
        encode_text_style(TextStyle(font_ref=2, screen_font_ref=2, arrow_type=-1), 2)


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("hide_out_of_plane_value", "out-of-plane tolerance must be finite"),
        ("hide_small_value", "small-value tolerance must be finite"),
    ],
)
def test_dimension_style_rejects_non_finite_tolerances(field: str, message: str) -> None:
    style = DimensionStyle(font_ref=2)
    setattr(style, field, float("nan"))
    with pytest.raises(ValueError, match=message):
        encode_dimension_style(style, 1)
