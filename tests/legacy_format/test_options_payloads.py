# SPDX-License-Identifier: MIT
"""Independent wire tests for legacy option typed values."""

from __future__ import annotations

import io
import struct

import pytest

from skppy.parser_legacy.options_payloads import read_typed_value


@pytest.mark.parametrize(
    ("type_code", "wire_format", "wire_value", "expected"),
    (
        (2, "<B", 0xA5, 0xA5),  # unsigned byte
        (3, "<H", 0xA5B6, 0xA5B6),  # unsigned 16-bit integer
        (4, "<I", 0xA5B6C7D8, 0xA5B6C7D8),  # unsigned 32-bit integer
        (5, "<f", 1.25, 1.25),  # 32-bit float
        (6, "<d", 2.5, 2.5),  # primary 64-bit float code
        (7, "<?", True, True),  # boolean
        (8, "<I", 0x11223344, 0x11223344),  # packed u32 semantic value
        (9, "<I", 0x55667788, 0x55667788),  # packed u32 semantic value
        (12, "<d", 12.5, 12.5),  # f64 semantic aliases
        (13, "<d", 13.5, 13.5),
        (14, "<d", 14.5, 14.5),
        (15, "<d", 15.5, 15.5),
        (16, "<d", 16.5, 16.5),
    ),
)
def test_read_typed_value_decodes_scalar_wire_codes(
    type_code: int,
    wire_format: str,
    wire_value: object,
    expected: object,
) -> None:
    data = struct.pack("<B", type_code) + struct.pack(wire_format, wire_value)

    assert read_typed_value(io.BytesIO(data)) == pytest.approx(expected)


def test_read_typed_value_decodes_null_string_and_nested_array() -> None:
    # Legacy strings use UTF-16LE BOM, 0xFF marker, one-byte UTF-16 unit count.
    encoded_text = b"\xff\xfe\xff" + struct.pack("<B", 2) + "UV".encode("utf-16le")
    nested = struct.pack("<BIBB", 11, 2, 2, 7) + struct.pack("<B", 10) + encoded_text

    assert read_typed_value(io.BytesIO(struct.pack("<B", 0))) is None
    assert read_typed_value(io.BytesIO(struct.pack("<B", 10) + encoded_text)) == "UV"
    assert read_typed_value(io.BytesIO(nested)) == (7, "UV")


@pytest.mark.parametrize("type_code", (17, 18, 19))
def test_read_typed_value_decodes_three_component_values(type_code: int) -> None:
    data = struct.pack("<B3d", type_code, 1.0, 2.0, 3.0)

    assert read_typed_value(io.BytesIO(data)) == (1.0, 2.0, 3.0)


def test_read_typed_value_decodes_sixteen_component_matrix() -> None:
    values = tuple(float(value) for value in range(16))
    data = struct.pack("<B16d", 20, *values)

    assert read_typed_value(io.BytesIO(data)) == values


def test_read_typed_value_rejects_unknown_code_at_record_offset() -> None:
    with pytest.raises(ValueError, match="type 99 at offset 0"):
        read_typed_value(io.BytesIO(struct.pack("<B", 99)))
