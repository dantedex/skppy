# SPDX-License-Identifier: MIT
"""Tests for automatic SKP container dispatch."""

from __future__ import annotations

import io
import struct
import zipfile

import pytest

import skppy.loader as loader
from skppy.data_structure.header import SkpHeader
from skppy.data_structure.document import SkpZipEntry
from skppy.data_structure.model import Model
from skppy.exceptions import InvalidSkpError, LoadCancelledError


def _legacy_string(text: str) -> bytes:
    # Legacy CString: UTF-16LE BOM, 0xFF marker, u8 code-unit count, payload.
    return b"\xff\xfe\xff" + struct.pack("<B", len(text)) + text.encode("utf-16le")


def test_load_dispatches_zip_container_to_modern_parser(tmp_path, monkeypatch):
    """Do not send a valid ZIP-based SKP through the legacy parser."""
    filepath = tmp_path / "modern.skp"
    with zipfile.ZipFile(filepath, "w") as archive:
        archive.writestr("model.dat", b"modern-model")

    header = SkpHeader(
        product_name="SketchUp Model",
        version_string="{26.0.0}",
        version_tuple=(26, 0, 0),
        vff_magic="VFF",
        vff_field_1=0,
        vff_field_2=0,
        vff_field_3=0,
        vff_field_4=0,
        zip_offset=0,
    )
    expected = Model(header=header)
    monkeypatch.setattr(loader, "parse_header", lambda stream, locate_zip: header)
    model_entry = SkpZipEntry(
        name="model.dat",
        file_size=12,
        compress_size=12,
        crc=0,
        is_dir=False,
    )
    monkeypatch.setattr(loader, "read_zip_entries", lambda path: ([], model_entry))

    def parse_modern(model_data, archive, parsed_header, document, *, import_vray_materials):
        assert model_data == b"modern-model"
        assert parsed_header is header
        assert document.filepath == str(filepath)
        assert import_vray_materials is False
        return expected

    monkeypatch.setattr(loader, "parse_model", parse_modern)

    def reject_legacy(data, *, import_vray_materials):
        raise AssertionError("legacy parser called for ZIP container")

    monkeypatch.setattr(loader, "parse_legacy_bytes", reject_legacy)

    assert loader.load(filepath) is expected


def test_load_dispatches_pathlike_non_zip_to_legacy_parser(tmp_path, monkeypatch):
    """Accept PathLike input and rewind it before reading the legacy payload."""
    filepath = tmp_path / "legacy.skp"
    filepath.write_bytes(b"legacy-model")
    expected = Model()

    def parse_legacy(data, *, import_vray_materials):
        assert data == b"legacy-model"
        assert import_vray_materials is True
        return expected

    monkeypatch.setattr(loader, "parse_legacy_bytes", parse_legacy)

    assert loader.load(filepath, import_vray_materials=True) is expected


def test_load_dispatches_legacy_header_with_appended_zip_to_legacy_parser(tmp_path, monkeypatch):
    """Trust the legacy SketchUp header when unrelated ZIP data is appended."""
    filepath = tmp_path / "legacy-with-metadata.skp"
    legacy_prefix = _legacy_string("SketchUp Model") + _legacy_string("{16.0.1}") + b"legacy archive"
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as archive:
        archive.writestr("document.xml", "<classificationDocument/>")
    payload = legacy_prefix + zip_buffer.getvalue()
    filepath.write_bytes(payload)
    expected = Model()

    def parse_legacy(data, *, import_vray_materials):
        assert data == payload
        assert import_vray_materials is False
        return expected

    monkeypatch.setattr(loader, "parse_legacy_bytes", parse_legacy)

    assert loader.load(filepath) is expected


def test_load_missing_pathlike_raises_file_not_found(tmp_path):
    """Preserve the standard filesystem exception for a missing Path."""
    with pytest.raises(FileNotFoundError):
        loader.load(tmp_path / "missing.skp")


def test_load_honors_cancellation_without_reporting_invalid_input(tmp_path):
    """Keep user cancellation distinct from malformed SKP failures."""
    filepath = tmp_path / "cancelled.skp"
    filepath.write_bytes(b"parser should never consume this")

    with pytest.raises(LoadCancelledError, match="cancelled"):
        loader.load(filepath, cancellation_check=lambda: True)


def test_load_rejects_zip_without_model_dat(tmp_path):
    """Normalize a malformed ZIP container into the public loader error."""
    filepath = tmp_path / "missing-model.skp"
    with zipfile.ZipFile(filepath, "w") as archive:
        archive.writestr("metadata.xml", "<metadata/>")

    with pytest.raises(InvalidSkpError, match=r"Could not decode a valid SKP"):
        loader.load(filepath)


def test_load_normalizes_invalid_legacy_bytes(tmp_path):
    """Do not expose low-level CArchive decoding errors from ``skppy.load``."""
    filepath = tmp_path / "invalid.skp"
    filepath.write_bytes(b"not a SketchUp model")

    with pytest.raises(InvalidSkpError, match=r"invalid\.skp"):
        loader.load(filepath)


def test_load_normalizes_truncated_modern_model_data(tmp_path):
    """Wrap a malformed TLV root from an otherwise valid ZIP container."""
    filepath = tmp_path / "truncated-modern.skp"
    # 0x01F4 is model root; its declared 64-byte payload is deliberately short.
    malformed_root = struct.pack("<HI", 0x01F4, 64) + b"short"
    with zipfile.ZipFile(filepath, "w") as archive:
        archive.writestr("model.dat", malformed_root)

    with pytest.raises(InvalidSkpError) as caught:
        loader.load(filepath)

    assert isinstance(caught.value.__cause__, ValueError)


def test_load_normalizes_truncated_legacy_archive(tmp_path):
    """Wrap a recognizable pre-ZIP header whose CVersionMap is truncated."""
    filepath = tmp_path / "truncated-legacy.skp"
    filepath.write_bytes(_legacy_string("SketchUp Model") + _legacy_string("{8.0.1}") + bytes(range(16)) + b"\xff")

    with pytest.raises(InvalidSkpError) as caught:
        loader.load(filepath)

    assert isinstance(caught.value.__cause__, (EOFError, ValueError))
