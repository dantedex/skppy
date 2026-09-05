# SPDX-License-Identifier: MIT
"""Small adversarial inputs verify resource limits without large allocations."""

import io
import zipfile

import pytest

import skppy
from skppy._bounded_io import BoundedZipFile, InputLimitError, read_bounded
from skppy._cancellation import cancellation_scope


@pytest.mark.parametrize("value", [0, -1, 1.5])
def test_load_limits_reject_invalid_budgets(value) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        skppy.LoadLimits(max_entry_bytes=value)


def test_chunk_reader_rejects_actual_oversize() -> None:
    with pytest.raises(InputLimitError, match="input byte limit"):
        read_bounded(io.BytesIO(b"12345"), 4, "data")
    assert read_bounded(io.BytesIO(b"1234"), 4, "data") == b"1234"


def test_zip_rejects_xml_before_opening_payload(tmp_path, monkeypatch) -> None:
    path = tmp_path / "material.skm"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("document.xml", b"x" * 1000)

    def fail_open(*args, **kwargs):
        raise AssertionError("oversized resource must not be opened")

    monkeypatch.setattr(BoundedZipFile, "open", fail_open)
    with pytest.raises(skppy.InvalidSkmError) as error:
        skppy.load_material(path, limits=skppy.LoadLimits(max_xml_bytes=10))
    assert isinstance(error.value.__cause__, InputLimitError)


def test_archive_limits_cumulative_reads_and_accepts_zipinfo(tmp_path) -> None:
    path = tmp_path / "resources.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("a.bin", b"123")
    with BoundedZipFile(path, limits=skppy.LoadLimits(max_total_bytes=5)) as archive:
        assert archive.read(archive.getinfo("a.bin")) == b"123"
        with pytest.raises(InputLimitError, match="input byte limit"):
            archive.read("a.bin")


def test_legacy_load_obeys_entry_limit(tmp_path) -> None:
    path = tmp_path / "legacy.skp"
    path.write_bytes(b"not a zip")
    with pytest.raises(skppy.InvalidSkpError) as error:
        skppy.load(path, limits=skppy.LoadLimits(max_entry_bytes=3))
    assert isinstance(error.value.__cause__, InputLimitError)


def test_corrupt_zip_reads_still_consume_budget(tmp_path) -> None:
    path = tmp_path / "corrupt.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("a.bin", b"123")
    with BoundedZipFile(path, limits=skppy.LoadLimits(max_total_bytes=3)) as archive:
        archive.getinfo("a.bin").CRC ^= 1
        with pytest.raises(zipfile.BadZipFile, match="CRC"):
            archive.read("a.bin")
        with pytest.raises(InputLimitError):
            archive.read("a.bin")


def test_material_load_can_be_cancelled_before_reading(tmp_path) -> None:
    with pytest.raises(skppy.LoadCancelledError):
        skppy.load_material(tmp_path / "unused.skm", cancellation_check=lambda: True)


def test_material_xml_parser_honors_increased_budget(tmp_path) -> None:
    path = tmp_path / "large-metadata.skm"
    xml = b'<materialDocument><material name="Large"/><!--' + b" " * (8 * 1024 * 1024) + b"--></materialDocument>"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("document.xml", xml)
    material = skppy.load_material(path, limits=skppy.LoadLimits(max_xml_bytes=len(xml)))
    assert material.name == "Large"


def test_chunk_reader_checks_cancellation_during_read() -> None:
    checks = iter([False, False, True])
    with cancellation_scope(lambda: next(checks)):
        with pytest.raises(skppy.LoadCancelledError):
            read_bounded(io.BytesIO(b"x" * 70000), 100000, "data")
