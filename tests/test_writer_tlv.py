# SPDX-License-Identifier: MIT
"""Tests for independent modern TLV encoders."""

from __future__ import annotations

import struct

import pytest

from skppy.writer.tlv import (
    encode_bool,
    encode_compact_int,
    encode_record,
    encode_records,
)


def test_encode_record_uses_little_endian_tag_and_length() -> None:
    """Match the documented six-byte TLV framing exactly."""
    assert encode_record(0x1234, b"abc") == struct.pack("<HI", 0x1234, 3) + b"abc"
    assert encode_records([(1, b"a"), (2, b"bc")]) == (
        struct.pack("<HI", 1, 1) + b"a" + struct.pack("<HI", 2, 2) + b"bc"
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, b"\x00"),
        (0xFF, b"\xff"),
        (0x100, b"\x00\x01"),
        (0xFFFFFF, b"\xff\xff\xff"),
        (0xFFFFFFFF, b"\xff\xff\xff\xff"),
    ],
)
def test_encode_compact_int_uses_minimum_width(value: int, expected: bytes) -> None:
    """Use the shortest non-empty little-endian scalar payload."""
    assert encode_compact_int(value) == expected


def test_scalar_encoders_reject_out_of_range_values() -> None:
    """Reject values that cannot be represented instead of truncating them."""
    with pytest.raises(ValueError, match="fit in u16"):
        encode_record(0x10000)
    with pytest.raises(ValueError, match="fit in u32"):
        encode_compact_int(-1)
    assert encode_bool(False) == b"\x00"
    assert encode_bool(True) == b"\x01"


def test_record_rejects_payload_larger_than_u32() -> None:
    class OversizedPayload:
        def __len__(self) -> int:
            return 0x1_0000_0000

    with pytest.raises(ValueError, match="payload is too large"):
        encode_record(1, OversizedPayload())  # type: ignore[arg-type]
