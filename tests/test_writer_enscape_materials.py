# SPDX-License-Identifier: MIT
"""Independent XML and public writer checks for observed Enscape metadata."""

from __future__ import annotations

from copy import deepcopy
import struct
import xml.etree.ElementTree as ET
import zipfile

import pytest

from skppy import AttributeDictionary, AttributeDictionaryEntry, Color, Material, Texture, new_model
from skppy.writer.enscape_materials import append_enscape_xml, enscape_material_xml, prepare_enscape_export

# Observed MaterialData fields, independently authored rather than parser-derived.
_PAINT_XML = (
    '<SketchupMaterial Version="5"><Type>GENERIC</Type><TypeV5>GENERIC</TypeV5>'
    "<Opacity>0.75</Opacity><DiffuseColor>#804000</DiffuseColor><ImageFade>0.5</ImageFade>"
    "<EmissiveColor>#000000</EmissiveColor><EmissiveStrength>0</EmissiveStrength>"
    "<TintColor>#C0C0C0</TintColor><Roughness>0.25</Roughness><BumpAmount>-0.5</BumpAmount>"
    "<NormalMapIntensity>2</NormalMapIntensity><Metallic>0.5</Metallic><Specular>0.25</Specular>"
    "<IndexOfRefraction>2</IndexOfRefraction><IsSolidGlass>false</IsSolidGlass>"
    "<BumpMapType>UNDEFINED</BumpMapType><TextureWidth>0</TextureWidth><TextureHeight>0</TextureHeight>"
    "</SketchupMaterial>"
)
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c63a8afafff0f00057b027de084ccea0000000049454e44ae426082"
)


def _paint() -> Material:
    return Material(
        id=1,
        name="Paint",
        color=Color(128, 64, 0),
        alpha=0.75,
        metallic=0.5,
        roughness=0.25,
        specular=0.25,
        ior=2,
        tint_color=Color(192, 192, 192),
        texture_fade=0.5,
        bump_strength=-0.5,
        normal_scale=2,
    )


def test_scalar_xml_matches_observed_layout() -> None:
    assert enscape_material_xml(_paint()).encode() == _PAINT_XML.encode()


def test_glass_xml_uses_transmission_instead_of_surface_alpha() -> None:
    material = _paint()
    material.alpha = 1
    material.transmission = 0.25
    expected = _PAINT_XML.replace("<TypeV5>GENERIC</TypeV5>", "<TypeV5>GLASS</TypeV5>")
    assert enscape_material_xml(material).encode() == expected.encode()


def test_emissive_xml_uses_observed_version_four_material_type() -> None:
    material = _paint()
    material.emission_color = Color(255, 128, 0)
    material.emission_strength = 5000
    expected = (
        _PAINT_XML.replace(
            'Version="5"><Type>GENERIC</Type><TypeV5>GENERIC</TypeV5>',
            'Version="4"><Type>SELF_ILLUMINATED</Type>',
        )
        .replace("#000000</EmissiveColor>", "#FF8000</EmissiveColor>")
        .replace(
            "<EmissiveStrength>0</EmissiveStrength>",
            "<EmissiveStrength>5000</EmissiveStrength>",
        )
    )
    assert enscape_material_xml(material).encode() == expected.encode()


def test_host_texture_xml_escapes_basename_and_converts_inches_to_meters() -> None:
    material = _paint()
    material.has_texture = True
    material.texture = Texture(
        filename=r"C:\textures\tile&.png",
        data=_PNG,
        x_scale=-5000,
        y_scale=10000,
        brightness=0.5,
        inverted=True,
    )
    expected = _PAINT_XML.replace(
        "</SketchupMaterial>",
        "<DiffuseTexture><Source>SKETCHUP</Source><Filepath>tile&amp;.png</Filepath>"
        "<Brightness>0.5</Brightness><IsInverted>true</IsInverted>"
        "<UseExplicitTransformation>false</UseExplicitTransformation><Width>127</Width><Height>254</Height>"
        "<Rotation>0</Rotation></DiffuseTexture></SketchupMaterial>",
    )
    assert enscape_material_xml(material).encode() == expected.encode()


def test_modern_xml_attribute_uses_sdk_string_type_and_escapes_nested_xml() -> None:
    element = ET.Element("material")
    append_enscape_xml(element, '<SketchupMaterial Version="5"><Filepath>a&amp;b</Filepath></SketchupMaterial>')
    expected = (
        b'<material><n0:AttributeDictionaries xmlns:n0="http://sketchup.google.com/schemas/1.0/types" count="1">'
        b'<n0:AttributeDictionary name="Enscape.Material" count="1"><n0:Attribute key="MaterialData" type="10">'
        b'&lt;SketchupMaterial Version="5"&gt;&lt;Filepath&gt;a&amp;amp;b&lt;/Filepath&gt;&lt;/SketchupMaterial&gt;'
        b"</n0:Attribute></n0:AttributeDictionary></n0:AttributeDictionaries></material>"
    )
    assert ET.tostring(element) == expected


def test_export_projection_replaces_only_owned_dictionary_without_mutation() -> None:
    model = new_model()
    material = _paint()
    material.alpha = 1
    material.transmission = 0.5
    material.has_texture = True
    material.texture = Texture(filename="paint.png", data=_PNG, brightness=2, inverted=True)
    model.materials.append(material)
    retained = AttributeDictionary(
        name="UserData", entries=[AttributeDictionaryEntry(key="key", string_value="value", value_type=3)]
    )
    stale = AttributeDictionary(name="Enscape.Material")
    model.attribute_dictionaries_by_object_id[material.id] = [stale, retained]
    original_material = deepcopy(material)
    prepared, material_data = prepare_enscape_export(model, export_vray_materials=False)
    assert model.materials == [original_material]
    assert model.attribute_dictionaries_by_object_id[material.id] == [stale, retained]
    assert prepared.entities is model.entities
    assert prepared.materials[0].alpha == 0.5
    assert prepared.materials[0].transmission == 0
    assert prepared.materials[0].specular == 0.5
    assert prepared.materials[0].texture is not material.texture
    assert prepared.materials[0].texture.brightness == 1
    assert prepared.materials[0].texture.inverted is False
    dictionaries = prepared.attribute_dictionaries_by_object_id[material.id]
    assert dictionaries[0] is retained
    assert dictionaries[1] == AttributeDictionary(
        name="Enscape.Material",
        entries=[AttributeDictionaryEntry(key="MaterialData", value_type=3, string_value=material_data[1])],
    )


@pytest.mark.parametrize("format", ["modern", "sketchup_2017"])
def test_public_save_writes_expected_material_data_bytes(tmp_path, format) -> None:
    model = new_model()
    model.materials.append(_paint())
    destination = tmp_path / "paint.skp"
    assert model.save(destination, format=format, export_enscape_materials=True) == destination
    if format == "modern":
        with zipfile.ZipFile(destination) as archive:
            xml = archive.read("materials/Paint/material.xml")
            raw = archive.read("model.dat")
        escaped = _PAINT_XML.replace("<", "&lt;").replace(">", "&gt;").encode()
        assert b'<n0:Attribute key="MaterialData" type="10">' + escaped + b"</n0:Attribute>" in xml
        # Complete string-valued attribute record: 0x38a4 wraps 0x38ad UTF-8.
        text = _PAINT_XML.encode()
        assert struct.pack("<HIHI", 0x38A4, len(text) + 6, 0x38AD, len(text)) + text in raw
    else:
        raw = destination.read_bytes()
        # CArchive unicode string header: FF FE FF, u16 extended length.
        text = _PAINT_XML.encode("utf-16-le")
        assert b"\xff\xfe\xff\xff" + struct.pack("<H", len(_PAINT_XML)) + text in raw
    assert model.materials[0] == _paint()


@pytest.mark.parametrize("format", ["modern", "sketchup_2017"])
def test_enscape_export_remains_opt_in_and_options_are_exclusive(tmp_path, format) -> None:
    model = new_model()
    model.materials.append(_paint())
    destination = tmp_path / "paint.skp"
    destination.write_bytes(b"existing")
    with pytest.raises(ValueError, match="unsupported export properties"):
        model.save(destination, format=format)
    with pytest.raises(ValueError, match="either Enscape or V-Ray"):
        model.save(destination, format=format, export_enscape_materials=True, export_vray_materials=True)
    assert destination.read_bytes() == b"existing"


@pytest.mark.parametrize("format", ["modern", "sketchup_2017"])
def test_public_export_embeds_original_host_pixels_with_adjustment_metadata(tmp_path, format) -> None:
    model = new_model()
    material = _paint()
    material.has_texture = True
    material.texture = Texture(filename="paint.png", data=_PNG, brightness=0.5, inverted=True)
    model.materials.append(material)
    destination = model.save(tmp_path / "textured.skp", format=format, export_enscape_materials=True)
    if format == "modern":
        with zipfile.ZipFile(destination) as archive:
            assert archive.read("materials/Paint/paint.png") == _PNG
            raw = archive.read("model.dat")
        assert b"<Brightness>0.5</Brightness><IsInverted>true</IsInverted>" in raw
    else:
        raw = destination.read_bytes()
        assert struct.pack("<II", 4, len(_PNG)) + _PNG in raw
        assert "<Brightness>0.5</Brightness><IsInverted>true</IsInverted>".encode("utf-16-le") in raw
    assert material.texture.brightness == 0.5
    assert material.texture.inverted is True


@pytest.mark.parametrize("format", ["modern", "sketchup_2017"])
def test_default_export_does_not_generate_enscape_metadata(tmp_path, format) -> None:
    model = new_model()
    model.add_material("Plain")
    destination = model.save(tmp_path / "plain.skp", format=format)
    if format == "modern":
        with zipfile.ZipFile(destination) as archive:
            assert b"Enscape.Material" not in archive.read("model.dat")
            assert b"Enscape.Material" not in archive.read("materials/Plain/material.xml")
    else:
        assert "Enscape.Material".encode("utf-16-le") not in destination.read_bytes()


@pytest.mark.parametrize(
    "field",
    [
        "metallic_texture",
        "roughness_texture",
        "normal_texture",
        "bump_texture",
        "displacement_texture",
        "opacity_texture",
    ],
)
def test_auxiliary_maps_are_rejected_until_resource_layout_is_verified(field) -> None:
    material = _paint()
    setattr(material, field, Texture(filename="map.png", data=_PNG))
    with pytest.raises(ValueError, match=field):
        enscape_material_xml(material)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"bump_map_type": "BUMP"}, "relief"),
        ({"displacement_scale": 0.5}, "relief"),
        ({"transmission": 0.5}, "independent alpha"),
        ({"transmission": 0.5, "alpha": 1, "emission_strength": 10}, "self illumination"),
        ({"tint_color": Color(255, 255, 255, 0)}, "alpha channel"),
        ({"emission_color": Color(255, 255, 255, 0)}, "alpha channel"),
        ({"ior": 0}, "ior"),
        ({"ior": -1}, "ior"),
        ({"ior": float("inf")}, "ior"),
        ({"normal_scale": -1}, "normal_scale"),
        ({"emission_strength": float("nan")}, "emission_strength"),
        ({"bump_strength": float("inf")}, "bump_strength"),
        ({"color": Color(256, 0, 0)}, "color channels"),
        ({"color": Color(0.5, 0, 0)}, "color channels"),
    ],
)
def test_unsupported_and_invalid_properties_are_rejected(changes, message) -> None:
    material = _paint()
    for key, value in changes.items():
        setattr(material, key, value)
    with pytest.raises(ValueError, match=message):
        enscape_material_xml(material)


@pytest.mark.parametrize("field", ["alpha", "metallic", "roughness", "specular", "texture_fade", "transmission"])
@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf")])
def test_factors_must_be_finite_and_in_range(field, value) -> None:
    material = Material()
    setattr(material, field, value)
    with pytest.raises(ValueError, match=field):
        enscape_material_xml(material)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"uv_scale": (2, 1)}, "uv_scale"),
        ({"brightness": -1}, "brightness"),
        ({"brightness": float("nan")}, "brightness"),
    ],
)
def test_unrepresentable_texture_properties_are_rejected(changes, message) -> None:
    material = Material(has_texture=True, texture=Texture(filename="paint.png", data=_PNG, **changes))
    with pytest.raises(ValueError, match=message):
        enscape_material_xml(material)
