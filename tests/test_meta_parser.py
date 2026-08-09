# SPDX-License-Identifier: MIT
"""Tests for modern ``meta/meta.dat`` metadata parsing."""

from __future__ import annotations

import zipfile

import pytest

from skppy.parser.meta_parser import (
    _extract_ascii_strings,
    _first_match,
    _looks_like_path,
    _strip_type_suffix,
    parse_meta_info,
    parse_meta_info_from_zip,
)


def _metadata_bytes() -> bytes:
    values = (
        b"SketchUp Pro",
        b"26.1.103",
        b"Meters",
        b"meta/model_thumbnail.pngP",
        b"meta/preview_thumbnail.png",
        b"temporary/model.skpxP",
        b"Alice",
        b"Model",
        b"ModelProperties",
        b"unclassified value",
    )
    return b"\x00\x01" + b"\x00".join(values) + b"\xff"


def test_parse_meta_info_classifies_known_and_unknown_strings() -> None:
    """Classify metadata while retaining complete contributor names."""
    meta = parse_meta_info(_metadata_bytes())

    assert meta.version_string == "26.1.103"
    assert meta.unit == "Meters"
    assert meta.application == "SketchUp"
    assert meta.model_thumbnail_path == "meta/model_thumbnail.png"
    assert meta.preview_thumbnail_path == "meta/preview_thumbnail.png"
    assert meta.temp_skpx_path == "temporary/model.skpx"
    assert meta.contributors == ["Alice", "unclassified value"]
    assert meta.unknown_values == meta.contributors
    assert "SketchUp Pro" in meta.raw_strings


def test_parse_meta_info_from_zip_reads_expected_entry(tmp_path) -> None:
    """Read metadata through the public ZIP convenience function."""
    model_path = tmp_path / "metadata.skp"
    with zipfile.ZipFile(model_path, "w") as archive:
        archive.writestr("meta/meta.dat", _metadata_bytes())

    meta = parse_meta_info_from_zip(str(model_path))

    assert meta.version_string == "26.1.103"
    assert meta.contributors == ["Alice", "unclassified value"]


def test_parse_meta_info_from_zip_requires_metadata_entry(tmp_path) -> None:
    """Expose a missing metadata entry as the documented ZIP error."""
    model_path = tmp_path / "no-metadata.skp"
    with zipfile.ZipFile(model_path, "w") as archive:
        archive.writestr("model.dat", b"")

    with pytest.raises(KeyError):
        parse_meta_info_from_zip(str(model_path))


def test_meta_helpers_handle_suffixes_patterns_and_paths() -> None:
    """Keep suffix handling narrow and helper edge cases deterministic."""
    assert _strip_type_suffix("ModelP") == "Model"
    assert _strip_type_suffix("thumbnail.pngP") == "thumbnail.png"
    assert _strip_type_suffix("123I") == "123"
    assert _strip_type_suffix("Alice") == "Alice"
    assert _strip_type_suffix("A") == "A"
    assert _strip_type_suffix("value1") == "value1"
    assert _extract_ascii_strings(b"abc\x00abcd\x00efgh", min_length=4) == [
        "abcd",
        "efgh",
    ]
    assert _first_match(["none", "v26.1.2"], r"\d+\.\d+\.\d+") == "26.1.2"
    assert _first_match(["none"], r"\d+") is None
    assert _looks_like_path("meta/file") is True
    assert _looks_like_path(r"meta\file") is True
    assert _looks_like_path("Alice") is False
