# SPDX-License-Identifier: MIT
"""Verify complete replacement and failure cleanup using literal file bytes."""

import os

import pytest

from skppy._atomic_io import atomic_write


@pytest.mark.parametrize("existing", [False, True])
def test_atomic_write_installs_complete_bytes(tmp_path, existing) -> None:
    path = tmp_path / "model.skp"
    if existing:
        path.write_bytes(b"old")
    atomic_write(path, b"new model")
    assert path.read_bytes() == b"new model"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("operation", ["fsync", "replace"])
def test_failed_write_keeps_previous_file_and_removes_temporary(tmp_path, monkeypatch, operation) -> None:
    path = tmp_path / "model.skp"
    path.write_bytes(b"old")

    def fail(*args):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(os, operation, fail)
    with pytest.raises(OSError, match="disk failure"):
        atomic_write(path, b"new")
    assert path.read_bytes() == b"old"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink and permission semantics")
def test_atomic_write_preserves_symlink_and_target_permissions(tmp_path) -> None:
    target = tmp_path / "target.skp"
    target.write_bytes(b"old")
    target.chmod(0o640)
    link = tmp_path / "link.skp"
    link.symlink_to(target)

    atomic_write(link, b"new")

    assert link.is_symlink()
    assert target.read_bytes() == b"new"
    assert target.stat().st_mode & 0o777 == 0o640
