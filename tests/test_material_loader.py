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


def _enscape_material_package(path: Path, *, relief_type: str = "NORMAL", bump_amount: float = 0.64) -> None:
    metadata = f"""<?xml version="1.0" encoding="utf-8"?>
<SketchupMaterial Version="4">
  <DiffuseColor>#405060</DiffuseColor><Opacity>0.6</Opacity>
  <TintColor>#B2B2B2</TintColor><ImageFade>0.845</ImageFade>
  <Roughness>0.72</Roughness><Metallic>0.31</Metallic><Specular>0.42</Specular>
  <IndexOfRefraction>1.61</IndexOfRefraction>
  <EmissiveColor>#102030</EmissiveColor><EmissiveStrength>2.5</EmissiveStrength>
  <BumpAmount>{bump_amount}</BumpAmount><NormalMapIntensity>0.83</NormalMapIntensity>
  <BumpMapType>{relief_type}</BumpMapType>
  <BumpTexture><Filepath>C:\\maps\\normal.png</Filepath><Brightness>0.8</Brightness><IsInverted>true</IsInverted></BumpTexture>
  <RoughnessTexture>
    <Filepath>C:\\maps\\roughness.png</Filepath><Brightness>0.65</Brightness><IsInverted>true</IsInverted>
  </RoughnessTexture>
</SketchupMaterial>"""
    xml = f"""<materialDocument>
  <material name="PBR Sample" colorRed="1" colorGreen="2" colorBlue="3" hasTexture="0">
    <AttributeDictionaries><AttributeDictionary name="Enscape.Material">
      <Attribute key="MaterialData"><![CDATA[{metadata}]]></Attribute>
    </AttributeDictionary></AttributeDictionaries>
  </material>
</materialDocument>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("document.xml", xml)
        archive.writestr("ref/ROUGHNESS.PNG", b"roughness pixels")


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


def test_loads_opt_in_enscape_pbr_values_and_embedded_maps(tmp_path: Path) -> None:
    path = tmp_path / "material.skm"
    _enscape_material_package(path)

    sketchup = skppy.load_material(path)
    material = skppy.load_material(path, import_vray_materials=True)

    assert (sketchup.metallic, sketchup.roughness) == pytest.approx((0.0, 1.0))
    assert (material.metallic, material.roughness, material.specular, material.ior) == pytest.approx(
        (0.31, 0.72, 0.42, 1.61)
    )
    assert material.color == skppy.Color(64, 80, 96)
    assert material.tint_color == skppy.Color(178, 178, 178)
    assert material.texture_fade == pytest.approx(0.845)
    assert sketchup.tint_color == skppy.Color(255, 255, 255)
    assert sketchup.texture_fade == 1
    assert material.alpha == pytest.approx(0.6)
    assert material.emission_color == skppy.Color(16, 32, 48)
    assert material.emission_strength == pytest.approx(2.5)
    assert material.bump_map_type == "NORMAL"
    assert (material.bump_strength, material.normal_scale) == pytest.approx((0.64, 0.83))
    assert material.roughness_texture is not None
    assert material.roughness_texture.filename == "roughness.png"
    assert material.roughness_texture.data == b"roughness pixels"
    assert material.roughness_texture.brightness == pytest.approx(0.65)
    assert material.roughness_texture.inverted is True
    assert material.normal_texture is not None
    assert material.normal_texture.filename == "normal.png"
    assert material.normal_texture.data is None
    assert material.normal_texture.brightness == pytest.approx(0.8)
    assert material.normal_texture.inverted is True


def test_maps_enscape_displacement_to_its_own_texture_slot(tmp_path: Path) -> None:
    path = tmp_path / "material.skm"
    _enscape_material_package(path, relief_type="DISPLACEMENT")

    material = skppy.load_material(path, import_vray_materials=True)

    assert material.bump_map_type == "DISPLACEMENT"
    assert material.displacement_scale == pytest.approx(0.64)
    assert material.displacement_texture is not None
    assert material.displacement_texture.filename == "normal.png"
    assert material.normal_texture is None


@pytest.mark.parametrize("relief", ["BUMP", "DISPLACEMENT"])
def test_negative_enscape_height_amounts_retain_relief_direction(tmp_path, relief) -> None:
    path = tmp_path / "negative.skm"
    _enscape_material_package(path, relief_type=relief, bump_amount=-0.75)

    material = skppy.load_material(path, import_vray_materials=True)

    assert material.bump_strength == pytest.approx(-0.75)
    if relief == "DISPLACEMENT":
        assert material.displacement_scale == pytest.approx(-0.75)


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
