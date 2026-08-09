# SPDX-License-Identifier: MIT
"""Modern text-style and dimension-style serialization."""

from __future__ import annotations

import struct
from math import isfinite

from ..data_structure.model_metadata import DimensionStyle, TextStyle
from ..parser.tlv import TlvTag
from .tlv import encode_bool, encode_compact_int, encode_record, encode_records


def encode_text_style(style: TextStyle, font_count: int) -> bytes:
    """Encode the payload of the root text-style block."""
    _validate_font_ref(style.font_ref, font_count, "Text style")
    _validate_font_ref(style.screen_font_ref, font_count, "Screen text style")
    _validate_u32_values(style.arrow_type, style.line_weight, style.leader_type)
    payload = encode_records(
        (
            (TlvTag.TEXT_STYLE_FONT_REF, encode_compact_int(style.font_ref)),
            (
                TlvTag.TEXT_STYLE_SCREEN_FONT_REF,
                encode_compact_int(style.screen_font_ref),
            ),
            (TlvTag.TEXT_STYLE_ARROW_TYPE, struct.pack("<I", style.arrow_type)),
            (TlvTag.TEXT_STYLE_LINE_WEIGHT, struct.pack("<I", style.line_weight)),
            (
                TlvTag.TEXT_STYLE_HIDE_OUT_OF_PLANE,
                encode_bool(style.hide_out_of_plane),
            ),
            (TlvTag.TEXT_STYLE_LEADER_TYPE, struct.pack("<I", style.leader_type)),
            (TlvTag.TEXT_STYLE_DISPLAY_LEADER, encode_bool(style.display_leader)),
            (TlvTag.TEXT_STYLE_COLOR, _encode_argb(style.color)),
            (TlvTag.TEXT_STYLE_SCREEN_COLOR, _encode_argb(style.screen_color)),
        )
    )
    return encode_record(TlvTag.TEXT_STYLE_RECORD, payload)


def encode_dimension_style(style: DimensionStyle, font_count: int) -> bytes:
    """Encode the payload of the root dimension-style block."""
    _validate_font_ref(style.font_ref, font_count, "Dimension style")
    _validate_u32_values(
        style.extension_offset,
        style.extension_overshoot,
        style.line_weight,
        style.arrow_type,
        style.arrow_size,
        style.text_position,
    )
    if not isfinite(style.hide_out_of_plane_value):
        raise ValueError("Dimension out-of-plane tolerance must be finite")
    if not isfinite(style.hide_small_value):
        raise ValueError("Dimension small-value tolerance must be finite")
    payload = encode_records(
        (
            (TlvTag.DIMENSION_STYLE_FONT_REF, encode_compact_int(style.font_ref)),
            (TlvTag.DIMENSION_STYLE_3D_TEXT, encode_bool(style.text_3d)),
            (
                TlvTag.DIMENSION_STYLE_ALWAYS_READABLE,
                encode_bool(style.always_readable),
            ),
            (
                TlvTag.DIMENSION_STYLE_EXTENSION_OFFSET,
                struct.pack("<I", style.extension_offset),
            ),
            (
                TlvTag.DIMENSION_STYLE_EXTENSION_OVERSHOOT,
                struct.pack("<I", style.extension_overshoot),
            ),
            (
                TlvTag.DIMENSION_STYLE_LINE_WEIGHT,
                struct.pack("<I", style.line_weight),
            ),
            (
                TlvTag.DIMENSION_STYLE_ARROW_TYPE,
                struct.pack("<I", style.arrow_type),
            ),
            (
                TlvTag.DIMENSION_STYLE_ARROW_SIZE,
                struct.pack("<I", style.arrow_size),
            ),
            (
                TlvTag.DIMENSION_STYLE_HIGHLIGHT_NON_ASSOC,
                encode_bool(style.highlight_non_associative),
            ),
            (
                TlvTag.DIMENSION_STYLE_HIGHLIGHT_NON_ASSOC_COLOR,
                _encode_argb(style.highlight_non_associative_color),
            ),
            (
                TlvTag.DIMENSION_STYLE_SHOW_RADIAL_PREFIX,
                encode_bool(style.show_radial_diameter_prefix),
            ),
            (
                TlvTag.DIMENSION_STYLE_HIDE_OUT_OF_PLANE,
                encode_bool(style.hide_out_of_plane),
            ),
            (
                TlvTag.DIMENSION_STYLE_HIDE_OUT_OF_PLANE_VALUE,
                struct.pack("<d", style.hide_out_of_plane_value),
            ),
            (TlvTag.DIMENSION_STYLE_HIDE_SMALL, encode_bool(style.hide_small)),
            (
                TlvTag.DIMENSION_STYLE_HIDE_SMALL_VALUE,
                struct.pack("<d", style.hide_small_value),
            ),
            (TlvTag.DIMENSION_STYLE_COLOR, _encode_argb(style.color)),
            (TlvTag.DIMENSION_STYLE_TEXT_COLOR, _encode_argb(style.text_color)),
            (
                TlvTag.DIMENSION_STYLE_TEXT_POSITION,
                struct.pack("<I", style.text_position),
            ),
        )
    )
    return encode_record(TlvTag.DIMENSION_STYLE_RECORD, payload)


def _validate_font_ref(value: int, font_count: int, label: str) -> None:
    if not 2 <= value < 2 + font_count:
        raise ValueError(f"{label} font reference does not identify a written font")


def _validate_u32_values(*values: int) -> None:
    if any(not isinstance(value, int) or not 0 <= value <= 0xFFFFFFFF for value in values):
        raise ValueError("Annotation-style integer values must fit in u32")


def _encode_argb(color: int) -> bytes:
    _validate_u32_values(color)
    return bytes(
        (
            (color >> 16) & 0xFF,
            (color >> 8) & 0xFF,
            color & 0xFF,
            (color >> 24) & 0xFF,
        )
    )
