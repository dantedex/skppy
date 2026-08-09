# SPDX-License-Identifier: MIT
"""Modern line-style manager serialization."""

from __future__ import annotations

import struct
from collections.abc import Iterable, Mapping
from math import isfinite

from ..data_structure.model_metadata import LineStyle
from ..parser.tlv import TlvTag
from .tlv import encode_bool, encode_compact_int, encode_record, encode_records

_BUILTIN_PATTERNS = (
    ("Solid Basic", "16.0"),
    ("Short dash", "6.0, -6.0"),
    ("Dash", "12.0, -6.0"),
    ("Dot", "1.0, -6.0"),
    ("Dash dot", "12.0, -6.0, 1.0, -6.0"),
    ("Dash double-dot", "12.0, -6.0, 1.0, -6.0, 1.0, -6.0"),
    (
        "Dash triple-dot",
        "12.0, -6.0, 1.0, -6.0, 1.0, -6.0, 1.0, -6.0",
    ),
    ("Double-dash dot", "12.0, -6.0, 12.0, -6.0, 1.0, -6.0"),
    (
        "Double-dash double-dot",
        "12.0, -6.0, 12.0, -6.0, 1.0, -6.0, 1.0, -6.0",
    ),
    (
        "Double-dash triple-dot",
        "12.0, -6.0, 12.0, -6.0, 1.0, -6.0, 1.0, -6.0, 1.0, -6.0",
    ),
    ("Long-dash dash", "36.0, -10.0, 12.0, -10.0"),
    (
        "Long-dash double-dash",
        "36.0, -10.0, 12.0, -10.0, 12.0, -10.0",
    ),
)
_BUILTIN_NAMES = frozenset(name for name, _ in _BUILTIN_PATTERNS)


def default_line_styles() -> list[LineStyle]:
    """Return the canonical immutable line styles occupying IDs 6-17."""
    return [LineStyle(name=name, dash_pattern=pattern, mutability=False) for name, pattern in _BUILTIN_PATTERNS]


def user_line_styles(styles: Iterable[LineStyle]) -> list[LineStyle]:
    """Return user styles, accepting exact parsed copies of built-ins."""
    values = list(styles)
    users = [style for style in values if style.name not in _BUILTIN_NAMES]
    supplied_builtins = [style for style in values if style.name in _BUILTIN_NAMES]
    canonical = {style.name: style for style in default_line_styles()}
    if any(style != canonical[style.name] for style in supplied_builtins):
        raise ValueError("Built-in line styles cannot be modified")
    names = [style.name for style in users]
    if len(names) != len(set(names)):
        raise ValueError("User line-style names must be unique")
    return users


def encode_line_style_record(style: LineStyle, serialized_id: int) -> bytes:
    """Encode one ``0x4076`` line-style record."""
    _validate_line_style(style)
    if serialized_id <= 0:
        raise ValueError("Serialized line-style IDs must be positive")
    payload = encode_records(
        (
            (
                TlvTag.ID_WRAPPER,
                encode_record(
                    TlvTag.ID_VALUE,
                    encode_compact_int(serialized_id),
                ),
            ),
            (TlvTag.LINE_STYLE_NAME, style.name.encode("utf-8")),
            (
                TlvTag.LINE_STYLE_DASH_PATTERN,
                style.dash_pattern.encode("utf-8"),
            ),
            (
                TlvTag.LINE_STYLE_LINE_WIDTH,
                struct.pack("<d", style.line_width_points),
            ),
            (
                TlvTag.LINE_STYLE_STIPPLE_SCALE,
                struct.pack("<d", style.stipple_scale),
            ),
            (TlvTag.LINE_STYLE_COLOR, _encode_color(style.color)),
            (TlvTag.LINE_STYLE_MUTABILITY, encode_bool(style.mutability)),
        )
    )
    return encode_record(TlvTag.LINE_STYLE_RECORD, payload)


def encode_line_styles(styles: Iterable[LineStyle], id_map: Mapping[int, int]) -> bytes:
    """Encode the complete manager with canonical built-ins and user styles."""
    users = user_line_styles(styles)
    if len(users) != len(id_map):
        raise ValueError("Line-style ID map must cover every user style")
    records = b"".join(
        encode_line_style_record(style, index) for index, style in enumerate(default_line_styles(), start=6)
    )
    records += b"".join(encode_line_style_record(style, id_map[id(style)]) for style in users)
    return encode_record(
        TlvTag.LINE_STYLES_RECORD,
        encode_record(TlvTag.LINE_STYLE_LIST, records),
    )


def _validate_line_style(style: LineStyle) -> None:
    if not style.name or "\x00" in style.name:
        raise ValueError("Line-style names must be non-empty and contain no NUL")
    if not style.dash_pattern or "\x00" in style.dash_pattern:
        raise ValueError("Line-style dash patterns must be non-empty")
    if not isfinite(style.stipple_scale) or style.stipple_scale == 0.0:
        raise ValueError("Line-style stipple scale must be finite and non-zero")
    if not isfinite(style.line_width_points) or style.line_width_points <= 0.0:
        raise ValueError("Line-style width must be finite and positive")
    if not isinstance(style.color, int) or not 0 <= style.color <= 0xFFFFFFFF:
        raise ValueError("Line-style color must fit in u32")


def _encode_color(color: int) -> bytes:
    return bytes(
        (
            (color >> 16) & 0xFF,
            (color >> 8) & 0xFF,
            color & 0xFF,
            (color >> 24) & 0xFF,
        )
    )
