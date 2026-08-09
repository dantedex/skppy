# SPDX-License-Identifier: MIT
"""Boundary tests for modern SKP header decoding."""

from __future__ import annotations

import io
import struct

import pytest

from skppy.exceptions import OldFormatError
from skppy.parser.header_parser import (
    _decode_prefixed_length,
    _find_zip_offset,
    _parse_raw_utf16le_strings,
    _parse_version_tuple,
    parse_header,
)


def _classic_string(text: str, *, byteorder: str = "little") -> bytes:
    bom = b"\xff\xfe" if byteorder == "little" else b"\xfe\xff"
    encoding = "utf-16le" if byteorder == "little" else "utf-16be"
    length_format = "<H" if byteorder == "little" else ">H"
    return bom + struct.pack(length_format, len(text)) + text.encode(encoding)


def test_parse_classic_header_and_locate_appended_zip() -> None:
    """Decode classic fields and scan padding before the ZIP signature."""
    payload = b"".join(
        (
            _classic_string("SketchUp Model"),
            _classic_string("{20.2.1}"),
            b"VFF",
            struct.pack("<HHHI", 1, 2, 3, 4),
            b"padding",
            b"PK\x03\x04",
        )
    )

    header = parse_header(io.BytesIO(payload))

    assert header.product_name == "SketchUp Model"
    assert header.version_tuple == (20, 2, 1)
    assert (header.vff_field_1, header.vff_field_4) == (1, 4)
    assert header.zip_offset == payload.index(b"PK\x03\x04")


def test_parse_big_endian_classic_strings() -> None:
    """Honor the BOM byte order for both length and string data."""
    payload = b"".join(
        (
            _classic_string("SketchUp Model", byteorder="big"),
            _classic_string("{8.0.0}", byteorder="big"),
            b"VFF",
            bytes(10),
        )
    )

    header = parse_header(io.BytesIO(payload), locate_zip=False)

    assert header.product_name == "SketchUp Model"
    assert header.version_tuple == (8, 0, 0)
    assert header.zip_offset is None


def test_parse_alternative_raw_header() -> None:
    """Decode modern raw UTF-16 text immediately before a ZIP archive."""
    text = "SketchUp Model {26.0.0}\n".encode("utf-16le")

    header = parse_header(io.BytesIO(text + b"PK\x03\x04"))

    assert header.product_name == "SketchUp Model"
    assert header.version_tuple == (26, 0, 0)
    assert header.vff_magic == "---"
    assert header.zip_offset == len(text)


def test_classic_header_without_vff_is_reported_as_legacy() -> None:
    """Reject pre-ZIP headers at the modern parser boundary."""
    stream = io.BytesIO(_classic_string("SketchUp Model") + _classic_string("{8.0.0}") + b"OLD" + bytes(10))
    stream.name = "legacy.skp"

    with pytest.raises(OldFormatError, match=r"legacy\.skp"):
        parse_header(stream)


@pytest.mark.parametrize("payload", [b"", b"\xff", b"\xff\xfe\x01"])
def test_truncated_header_raises_eof(payload: bytes) -> None:
    """Fail at the exact missing header boundary instead of guessing."""
    with pytest.raises(EOFError):
        parse_header(io.BytesIO(payload))


def test_header_helpers_cover_malformed_values_and_missing_zip() -> None:
    """Keep malformed version and scan behavior deterministic."""
    assert _parse_raw_utf16le_strings(b"A\x00{\x001\x00.\x002") == ("A", "{1.")
    assert _parse_version_tuple("{x.1}") is None
    assert _parse_version_tuple("  ") is None
    assert _decode_prefixed_length(b"\xff\x08", little_endian=True) == 8
    with pytest.raises(ValueError, match="2 bytes"):
        _decode_prefixed_length(b"\x01", little_endian=True)

    stream = io.BytesIO(b"no archive here")
    stream.seek(3)
    assert _find_zip_offset(stream) is None
    assert stream.tell() == 3
