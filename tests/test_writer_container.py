# SPDX-License-Identifier: MIT
"""Tests for modern VFF and ZIP container construction."""

from __future__ import annotations

import io
import struct
import zipfile

import pytest

from skppy import SkpHeader
from skppy.writer.container import (
    build_modern_container,
    encode_classic_header,
    write_modern_container,
)


def _header() -> SkpHeader:
    return SkpHeader(
        product_name="SketchUp Model",
        version_string="{26.1.103}",
        version_tuple=(26, 1, 103),
        vff_magic="VFF",
        vff_field_1=8,
        vff_field_2=1,
        vff_field_3=17,
        vff_field_4=0x2CAA_A153,
        zip_offset=None,
    )


def test_encode_classic_header_matches_wire_layout() -> None:
    """Encode both UTF-16 fields, VFF marker, and fixed scalar fields."""
    header = _header()
    expected = (
        b"\xff\xfe\xff\x0e"
        + "SketchUp Model".encode("utf-16-le")
        + b"\xff\xfe\xff\x0a"
        + "{26.1.103}".encode("utf-16-le")
        + b"VFF"
        + struct.pack("<HHHI", 8, 1, 17, 0x2CAA_A153)
    )

    assert encode_classic_header(header) == expected


def test_build_modern_container_matches_raw_prefix_and_zip_entries() -> None:
    """Create a deterministic prefixed ZIP checked without the SKP parser."""
    entries = {"model.dat": b"model payload", "meta/meta.dat": b"metadata"}

    first = build_modern_container(entries, _header())
    second = build_modern_container(entries, _header())

    assert first == second
    prefix = encode_classic_header(_header())
    assert first[: len(prefix)] == prefix
    assert first[len(prefix) : len(prefix) + 4] == b"PK\x03\x04"
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        assert archive.namelist() == list(entries)
        assert archive.read("model.dat") == b"model payload"


def test_container_rejects_missing_model_and_unsafe_names() -> None:
    """Require the core entry and prevent ambiguous ZIP paths."""
    with pytest.raises(ValueError, match=r"model\.dat"):
        build_modern_container({}, _header())
    with pytest.raises(ValueError, match="Unsafe"):
        build_modern_container({"model.dat": b"model", "../texture.png": b"image"}, _header())


def test_header_rejects_non_vff_and_non_bmp_values() -> None:
    """Fail before writing headers that the classic form cannot represent."""
    header = _header()
    header.vff_magic = "---"
    with pytest.raises(ValueError, match="requires a VFF"):
        encode_classic_header(header)

    header = _header()
    header.product_name = "SketchUp \U0001f3e0"
    with pytest.raises(ValueError, match="BMP"):
        encode_classic_header(header)

    header = _header()
    header.product_name = "x" * 256
    with pytest.raises(ValueError, match="cannot exceed 255"):
        encode_classic_header(header)


def test_write_modern_container_matches_raw_built_bytes(tmp_path) -> None:
    destination = tmp_path / "model.skp"
    entries = {"model.dat": b"raw model"}

    assert write_modern_container(destination, entries, _header()) == destination
    assert destination.read_bytes() == build_modern_container(entries, _header())
