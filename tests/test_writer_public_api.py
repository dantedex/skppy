# SPDX-License-Identifier: MIT
"""Tests for the public model persistence API."""

from __future__ import annotations

import io
import struct
import zipfile
from pathlib import Path

import pytest

import skppy


def test_save_and_model_save_write_raw_modern_containers(tmp_path: Path) -> None:
    """Expose both public entry points over the validated modern writer."""
    model = skppy.new_model()
    model.entities.add_face([(0, 0, 0), (1, 0, 0), (0, 1, 0)])

    first = tmp_path / "function.skp"
    assert skppy.save(model, first) == first

    second = tmp_path / "method.skp"
    assert model.save(second) == second
    assert first.read_bytes() == second.read_bytes()

    raw = first.read_bytes()
    expected_prefix = (
        b"\xff\xfe\xff\x0e"
        + "SketchUp Model".encode("utf-16-le")
        + b"\xff\xfe\xff\x0a"
        + "{26.1.103}".encode("utf-16-le")
        + b"VFF"
        + struct.pack("<HHHI", 8, 1, 17, 0x2CAA_A153)
    )
    assert raw.startswith(expected_prefix)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert "model.dat" in archive.namelist()
        assert struct.pack("<H", 0x0DAC) in archive.read("model.dat")


def test_save_does_not_touch_destination_when_validation_fails(tmp_path: Path) -> None:
    """Build the complete container before replacing destination contents."""
    model = skppy.new_model()
    model.scenes.append(skppy.Scene(id=1, name="Opaque", raw_payload=b"opaque"))
    destination = tmp_path / "existing.skp"
    destination.write_bytes(b"existing data")

    with pytest.raises(ValueError, match="not a valid TLV"):
        skppy.save(model, destination)
    assert destination.read_bytes() == b"existing data"


@pytest.mark.parametrize("output_format", ["modern", "sketchup_2017"])
def test_model_save_exports_vray_materials_for_each_public_format(tmp_path: Path, output_format: str) -> None:
    model = skppy.new_model()
    model.add_material("Paint", color=skppy.Color(255, 0, 0), metallic=0.5, roughness=0.25)
    destination = tmp_path / f"vray-{output_format}.skp"

    model.save(
        destination,
        format=output_format,  # type: ignore[arg-type]
        export_vray_materials=True,
    )
    raw = destination.read_bytes()

    if output_format == "modern":
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            raw = archive.read("materials/Paint/material.xml")
        encoding = "utf-8"
    else:
        encoding = "utf-16le"
    assert "VRayInfo".encode(encoding) in raw
    assert '"class":"BRDFVRayMtl"'.encode(encoding) in raw
