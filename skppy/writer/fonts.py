# SPDX-License-Identifier: MIT
"""Modern ``model.dat`` font encoders."""

from __future__ import annotations

import struct
from collections.abc import Iterable
from math import isfinite

from ..data_structure.model_metadata import Font
from ..parser.tlv import TlvTag
from .tlv import encode_bool, encode_compact_int, encode_record, encode_records


def default_fonts() -> list[Font]:
    """Return the two baseline fonts present in a new modern model."""
    return [
        Font(face_name="Arial", point_size=12, world_size=1.0),
        Font(face_name="Tahoma", point_size=12, world_size=1.0),
    ]


def encode_fonts(fonts: Iterable[Font]) -> bytes:
    """Encode the payload of a modern root font block.

    Font IDs are implicit in the shared data model, so the writer assigns them
    deterministically from 2. Those IDs match the baseline font references used
    by modern text and dimension defaults that will be serialized later.
    """
    records = []
    for font_id, font in enumerate(fonts, start=2):
        _validate_font(font)
        identity = encode_record(TlvTag.ID_VALUE, encode_compact_int(font_id))
        payload = encode_records(
            (
                (TlvTag.ID_WRAPPER, identity),
                (TlvTag.FONT_FACE_NAME, font.face_name.encode("utf-8")),
                (TlvTag.FONT_BOLD_FLAG, encode_bool(font.bold)),
                (TlvTag.FONT_ITALIC_FLAG, encode_bool(font.italic)),
                (TlvTag.FONT_POINT_SIZE, struct.pack("<I", font.point_size)),
                (TlvTag.FONT_USE_WORLD_SIZE, encode_bool(font.use_world_size)),
                (TlvTag.FONT_WORLD_SIZE, struct.pack("<d", font.world_size)),
            )
        )
        records.append((TlvTag.FONT_RECORD, payload))
    font_list = encode_record(TlvTag.FONTS_LIST, encode_records(records))
    return encode_record(TlvTag.FONTS_CONTAINER, font_list)


def _validate_font(font: Font) -> None:
    if not font.face_name:
        raise ValueError("Font face name cannot be empty")
    if not 0 <= font.point_size <= 0xFFFFFFFF:
        raise ValueError("Font point size must fit in u32")
    if not isfinite(font.world_size) or font.world_size < 0.0:
        raise ValueError("Font world size must be finite and non-negative")
