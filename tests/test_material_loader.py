# SPDX-License-Identifier: MIT
"""Standalone SketchUp material package tests."""

from __future__ import annotations

import json
from pathlib import Path
import zipfile

import pytest

import skppy


def _material_package(
    path: Path,
    *,
    suffix_name: str = "Sample",
    image_path: str = "texture_1.jpg",
) -> None:
    plugin = json.dumps(
        {
            "name": "/Sample/BRDF",
            "class": "BRDFVRayMtl",
            "params": {
                "metalness": "0.75",
                "option_use_roughness": "1",
                "reflect_glossiness": "0.2",
            },
        }
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<materialDocument xmlns="http://sketchup.google.com/schemas/sketchup/1.0/material"
                  xmlns:mat="http://sketchup.google.com/schemas/sketchup/1.0/material"
                  xmlns:t="http://sketchup.google.com/schemas/1.0/types">
  <mat:material name="{suffix_name}" colorRed="10" colorGreen="20" colorBlue="30"
                useTrans="1" trans="0.25" hasTexture="1">
    <mat:texture textureFilename="C:\\maps\\original.jpg" xScale="12.5" yScale="25">
      <mat:images><mat:image path="{image_path}" file_name="original.jpg" /></mat:images>
    </mat:texture>
    <t:AttributeDictionaries>
      <t:AttributeDictionary name="VRayPlugins">
        <t:Attribute key="/Sample/BRDF"><![CDATA[{plugin}]]></t:Attribute>
      </t:AttributeDictionary>
    </t:AttributeDictionaries>
  </mat:material>
</materialDocument>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("document.xml", xml)
        archive.writestr("ref/texture_1.jpg", b"jpeg texture")


@pytest.mark.parametrize("filename", ["material.skm", "material.skp"])
def test_loads_material_package_by_contents(tmp_path: Path, filename: str) -> None:
    path = tmp_path / filename
    _material_package(path, suffix_name="Internal Material Name")

    material = skppy.load_material(path)

    assert material.name == "Internal Material Name"
    assert material.color == skppy.Color(10, 20, 30)
    assert material.alpha == pytest.approx(0.75)
    assert material.has_texture is True
    assert material.texture is not None
    assert material.texture.filename == "original.jpg"
    assert material.texture.data == b"jpeg texture"
    assert (material.texture.x_scale, material.texture.y_scale) == pytest.approx((12.5, 25.0))
    assert (material.metallic, material.roughness) == pytest.approx((0.0, 1.0))


def test_loads_opt_in_vray_values_from_material_package(tmp_path: Path) -> None:
    path = tmp_path / "material.skm"
    _material_package(path)

    material = skppy.load_material(path, import_vray_materials=True)

    assert (material.metallic, material.roughness) == pytest.approx((0.75, 0.2))


def test_accepts_explicit_ref_texture_path(tmp_path: Path) -> None:
    path = tmp_path / "material.skm"
    _material_package(path, image_path="ref/texture_1.jpg")

    material = skppy.load_material(path)

    assert material.texture is not None
    assert material.texture.data == b"jpeg texture"


def test_rejects_material_texture_parent_traversal(tmp_path: Path) -> None:
    path = tmp_path / "material.skm"
    _material_package(path, image_path="../texture_1.jpg")

    with pytest.raises(skppy.InvalidSkmError, match="Could not decode a valid SKM") as caught:
        skppy.load_material(path)

    assert isinstance(caught.value.__cause__, ValueError)


def test_rejects_unrelated_zip_document(tmp_path: Path) -> None:
    """Do not mistake an SKP classification ZIP for a standalone material."""
    path = tmp_path / "model-metadata.skp"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("document.xml", "<classificationDocument/>")

    with pytest.raises(skppy.InvalidSkmError) as caught:
        skppy.load_material(path)

    assert isinstance(caught.value.__cause__, ValueError)


def test_missing_material_path_preserves_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        skppy.load_material(tmp_path / "missing.skm")


@pytest.mark.parametrize(
    ("contents", "cause_type"),
    [
        (b"not a zip", zipfile.BadZipFile),
        (None, KeyError),
    ],
)
def test_rejects_invalid_material_packages(tmp_path: Path, contents: bytes | None, cause_type: type[Exception]) -> None:
    path = tmp_path / "invalid.skm"
    if contents is None:
        with zipfile.ZipFile(path, "w"):
            pass
    else:
        path.write_bytes(contents)

    with pytest.raises(skppy.InvalidSkmError, match="Could not decode a valid SKM") as caught:
        skppy.load_material(path)

    assert isinstance(caught.value.__cause__, cause_type)
