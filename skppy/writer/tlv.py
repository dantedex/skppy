# SPDX-License-Identifier: MIT
"""Primitive encoders for modern SketchUp TLV records."""

from __future__ import annotations

import struct
from collections.abc import Iterable


def encode_record(tag: int, payload: bytes = b"") -> bytes:
    """Encode one ``u16 tag + u32 length + payload`` TLV record."""
    if not 0 <= tag <= 0xFFFF:
        raise ValueError(f"TLV tag must fit in u16, got {tag}")
    if len(payload) > 0xFFFFFFFF:
        raise ValueError("TLV payload is too large for its u32 length")
    return struct.pack("<HI", tag, len(payload)) + payload


def encode_records(records: Iterable[tuple[int, bytes]]) -> bytes:
    """Encode and concatenate records in their supplied order."""
    return b"".join(encode_record(tag, payload) for tag, payload in records)


def encode_compact_int(value: int) -> bytes:
    """Encode an unsigned integer in the shortest 1-4 byte LE payload."""
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError(f"Compact integer must fit in u32, got {value}")
    width = max(1, (value.bit_length() + 7) // 8)
    return value.to_bytes(width, "little")


def encode_bool(value: bool) -> bytes:
    """Encode a boolean as SketchUp's single-byte scalar payload."""
    return b"\x01" if value else b"\x00"
