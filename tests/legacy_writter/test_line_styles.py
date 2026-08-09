# SPDX-License-Identifier: MIT
"""Raw SU2017 compatibility-extension fixtures for line styles."""

import struct

import pytest

import skppy
from skppy.legacy_writter import build_legacy_2017_model


def test_custom_line_style_matches_raw_legacy_extension_payload() -> None:
    model = skppy.Model.new()
    model.line_styles = [
        skppy.LineStyle(
            name="Custom",
            dash_pattern="3,-2",
            stipple_scale=2,
            line_width_points=1.5,
            color=0x11223344,
            mutability=False,
        ),
    ]
    expected = (
        '{"line_styles":[{"color":287454020,"dash_pattern":"3,-2","line_width_points":1.5,'
        '"mutability":false,"name":"Custom","stipple_scale":2}]}'
    )

    encoded = build_legacy_2017_model(model)

    assert _raw_string(expected) in encoded


def _raw_string(value: str) -> bytes:
    payload = value.encode("utf-16le")
    length = len(value)
    prefix = bytes((length,)) if length < 0xFF else b"\xff" + struct.pack("<H", length)
    return b"\xff\xfe\xff" + prefix + payload


@pytest.mark.parametrize(
    ("styles", "message"),
    [
        ([skppy.LineStyle("Same", "1"), skppy.LineStyle("Same", "2")], "names must be unique"),
        ([skppy.LineStyle("", "1")], "names must be non-empty"),
        ([skppy.LineStyle("Style", "")], "dash patterns must be non-empty"),
        ([skppy.LineStyle("Style", "1", stipple_scale=0.0)], "scales and widths"),
        ([skppy.LineStyle("Style", "1", color=-1)], "color must fit"),
        ([skppy.LineStyle("Dash", "modified", mutability=False)], "built-in line styles cannot be modified"),
    ],
)
def test_rejects_invalid_custom_line_styles(styles: list[skppy.LineStyle], message: str) -> None:
    model = skppy.Model.new()
    model.line_styles = styles

    with pytest.raises(ValueError, match=message):
        build_legacy_2017_model(model)
