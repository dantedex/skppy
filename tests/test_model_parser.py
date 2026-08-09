# SPDX-License-Identifier: MIT
"""Tests for model-level modern TLV metadata parsing."""

from __future__ import annotations

import struct

from skppy.data_structure.model_metadata import RenderingOptions
from skppy.parser.rendering_options import parse_rendering_options

# 0x733C is a rendering-options record. The focused fields below are render
# mode (0x733D), texture visibility (0x7340), and background color (0x7357).


def _record(tag: int, payload: bytes) -> bytes:
    return struct.pack("<HI", tag, len(payload)) + payload


def _rendering_payload(*fields: bytes) -> bytes:
    record = _record(0x733C, b"".join(fields))
    return record


def test_rendering_options_keep_public_defaults_for_absent_tags() -> None:
    """Do not turn optional rendering settings into zero-valued settings."""
    payload = _rendering_payload(
        _record(0x733D, b"\x02"),
    )

    options = parse_rendering_options(payload)
    defaults = RenderingOptions()

    assert options.render_mode == 2
    assert options.texture is defaults.texture is True
    assert options.display_text is defaults.display_text is True
    assert options.display_dims is defaults.display_dims is True
    assert options.foreground_color == defaults.foreground_color == 0xFF000000
    assert options.highlight_color == defaults.highlight_color == 0xFF00FF00


def test_rendering_options_decode_present_false_and_rgba_color() -> None:
    """Distinguish an explicit false value and normalize packed RGBA colors."""
    payload = _rendering_payload(
        _record(0x7340, b"\x00"),
        _record(0x7357, b"\x11\x22\x33\x44"),
    )

    options = parse_rendering_options(payload)

    assert options.texture is False
    assert options.background_color == 0x44112233


def test_rendering_options_expose_named_section_display_bits() -> None:
    """Expose confirmed section-plane and section-cut mask semantics."""
    # 0x7375 is the section display mask: bit 0 is planes, bit 1 is cuts.
    options = parse_rendering_options(_rendering_payload(_record(0x7375, struct.pack("<I", 2))))

    assert options.display_section_planes is False
    assert options.display_section_cuts is True

    options.display_section_planes = True
    options.display_section_cuts = False

    assert options.section_display_mode == 1
