# SPDX-License-Identifier: MIT
"""Raw-byte checks for modern line-style serialization."""

from __future__ import annotations

import struct

import pytest

from skppy.data_structure.model_metadata import LineStyle
from skppy.writer.line_styles import (
    default_line_styles,
    encode_line_style_record,
    encode_line_styles,
    user_line_styles,
)


def _raw_record(tag: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HI", tag, len(payload)) + payload


def test_user_line_style_record_matches_raw_expected_bytes() -> None:
    style = LineStyle(
        name="Writer Dash",
        dash_pattern="12.0, -6.0",
        stipple_scale=2.0,
        line_width_points=2.5,
        color=0xFF0A141E,
        mutability=True,
    )
    payload = b"".join(
        (
            _raw_record(0x05DC, _raw_record(0x05DE, b"\x12")),
            _raw_record(0x4077, b"Writer Dash"),
            _raw_record(0x4078, b"12.0, -6.0"),
            _raw_record(0x407A, struct.pack("<d", 2.5)),
            _raw_record(0x4079, struct.pack("<d", 2.0)),
            _raw_record(0x407B, b"\x0a\x14\x1e\xff"),
            _raw_record(0x407C, b"\x01"),
        )
    )
    expected = _raw_record(0x4076, payload)

    assert encode_line_style_record(style, 18) == expected
    assert expected in encode_line_styles([style], {id(style): 18})


def test_line_style_manager_rejects_modified_builtins_and_duplicate_users() -> None:
    modified = default_line_styles()[0]
    modified.dash_pattern = "changed"
    with pytest.raises(ValueError, match="Built-in line styles cannot be modified"):
        user_line_styles([modified])

    first = LineStyle(name="User", dash_pattern="1, -1")
    second = LineStyle(name="User", dash_pattern="2, -2")
    with pytest.raises(ValueError, match="names must be unique"):
        user_line_styles([first, second])

    with pytest.raises(ValueError, match="map must cover"):
        encode_line_styles([first], {})


@pytest.mark.parametrize(
    ("changes", "serialized_id", "message"),
    [
        ({}, 0, "IDs must be positive"),
        ({"name": ""}, 18, "names must be non-empty"),
        ({"dash_pattern": ""}, 18, "patterns must be non-empty"),
        ({"stipple_scale": 0.0}, 18, "scale must be finite and non-zero"),
        ({"line_width_points": 0.0}, 18, "width must be finite and positive"),
        ({"color": -1}, 18, "color must fit in u32"),
    ],
)
def test_line_style_rejects_unrepresentable_values(changes: dict, serialized_id: int, message: str) -> None:
    style = LineStyle(name="User", dash_pattern="1, -1")
    for field, value in changes.items():
        setattr(style, field, value)
    with pytest.raises(ValueError, match=message):
        encode_line_style_record(style, serialized_id)
