# SPDX-License-Identifier: MIT
"""Tests for ZIP entry metadata and malformed containers."""

from __future__ import annotations

import zipfile

from skppy.parser.zip_entries import read_zip_entries


def test_read_zip_entries_reports_files_directories_and_model(tmp_path) -> None:
    """Expose central-directory metadata and locate model.dat by exact name."""
    filepath = tmp_path / "model.skp"
    with zipfile.ZipFile(filepath, "w") as archive:
        archive.writestr("model.dat", b"model")
        archive.writestr("images/", b"")

    entries, model_entry = read_zip_entries(filepath)

    assert [entry.name for entry in entries] == ["model.dat", "images/"]
    assert model_entry is not None
    assert model_entry.file_size == 5
    assert entries[1].is_dir is True


def test_read_zip_entries_returns_empty_for_bad_zip(tmp_path) -> None:
    """Keep low-level ZIP inspection recoverable for invalid data."""
    filepath = tmp_path / "invalid.skp"
    filepath.write_bytes(b"not a zip")

    assert read_zip_entries(filepath) == ([], None)
