# SPDX-License-Identifier: MIT
"""Enscape material metadata boundary tests."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

import skppy
from skppy.parser.enscape_materials import apply_enscape_xml


def _material_element(metadata: str | None) -> ET.Element:
    encoded = "" if metadata is None else f'<Attribute key="MaterialData"><![CDATA[{metadata}]]></Attribute>'
    return ET.fromstring(
        f'<material><AttributeDictionary name="Ignored"/><AttributeDictionary name="Enscape.Material">{encoded}'
        "</AttributeDictionary></material>"
    )


def _parse_xml(value: bytes) -> ET.Element:
    return ET.fromstring(value)


def _resolve_texture(filename: str, brightness: float, inverted: bool) -> skppy.Texture:
    return skppy.Texture(filename=filename, brightness=brightness, inverted=inverted)


@pytest.mark.parametrize("metadata", [None, "<", "<Other/>"])
def test_rejects_absent_malformed_and_unrelated_enscape_metadata(metadata: str | None) -> None:
    material = skppy.Material()

    assert not apply_enscape_xml(
        material,
        _material_element(metadata),
        parse_xml=_parse_xml,
        resolve_texture=_resolve_texture,
    )
    assert material == skppy.Material()


@pytest.mark.parametrize(("emission_color", "relief_type"), [("#123", "BUMP"), ("#GG0000", "UNKNOWN")])
def test_safely_defaults_invalid_enscape_fields(emission_color: str, relief_type: str) -> None:
    metadata = f"""<SketchupMaterial>
      <Metallic>nan</Metallic><Roughness>bad</Roughness><Specular>2</Specular>
      <IndexOfRefraction>0</IndexOfRefraction><EmissiveColor>{emission_color}</EmissiveColor>
      <BumpAmount>-2</BumpAmount><NormalMapIntensity>-3</NormalMapIntensity><BumpMapType>{relief_type}</BumpMapType>
      <BumpTexture><Filepath/></BumpTexture>
    </SketchupMaterial>"""
    material = skppy.Material(metallic=0.2, roughness=0.3, emission_color=skppy.Color(1, 2, 3))

    assert apply_enscape_xml(
        material,
        _material_element(metadata),
        parse_xml=_parse_xml,
        resolve_texture=_resolve_texture,
    )
    assert (material.metallic, material.roughness, material.specular, material.ior) == pytest.approx(
        (0.2, 0.3, 1.0, 1.5)
    )
    assert material.emission_color == skppy.Color(1, 2, 3)
    assert (material.emission_strength, material.bump_strength, material.normal_scale) == pytest.approx((0, -2, 0))
    assert material.bump_map_type == ("BUMP" if relief_type == "BUMP" else "NONE")
    assert material.bump_texture is None
    assert material.roughness_texture is None


@pytest.mark.parametrize("has_texture", [False, True])
def test_sketchup_source_uses_host_image_instead_of_stale_filename(has_texture: bool) -> None:
    metadata = """<SketchupMaterial><DiffuseTexture><Source>SKETCHUP</Source><Filepath>stale.png</Filepath>
      <Brightness>0.8</Brightness><IsInverted>true</IsInverted></DiffuseTexture>
      <RoughnessTexture><Source>SKETCHUP</Source></RoughnessTexture></SketchupMaterial>"""
    original = skppy.Texture(filename="actual.png", data=b"host pixels", x_scale=2, y_scale=3)
    material = skppy.Material(has_texture=has_texture, texture=original if has_texture else None)

    def reject_external_lookup(*args):
        raise AssertionError("SKETCHUP source must not resolve a filename")

    assert apply_enscape_xml(
        material, _material_element(metadata), parse_xml=_parse_xml, resolve_texture=reject_external_lookup
    )

    if has_texture:
        assert material.texture is not original
        assert material.texture.data == material.roughness_texture.data == b"host pixels"
        assert material.texture.filename == "actual.png"
        assert material.texture.brightness == pytest.approx(0.8)
        assert material.texture.inverted
        assert (material.roughness_texture.x_scale, material.roughness_texture.y_scale) == (2, 3)
        assert original.brightness == material.roughness_texture.brightness == 1
        assert not original.inverted and not material.roughness_texture.inverted
    else:
        assert material.texture is material.roughness_texture is None


@pytest.mark.parametrize(("fade", "expected"), [("0", 0), ("0.845", 0.845), ("2", 1), ("-1", 0), ("nan", 1)])
def test_imports_tint_and_bounds_image_fade(fade: str, expected: float) -> None:
    metadata = f"""<SketchupMaterial Version="5"><TintColor>#B2B2B2</TintColor><ImageFade>{fade}</ImageFade>
      </SketchupMaterial>"""
    material = skppy.Material()

    assert apply_enscape_xml(
        material, _material_element(metadata), parse_xml=_parse_xml, resolve_texture=_resolve_texture
    )

    assert material.tint_color == skppy.Color(178, 178, 178)
    assert material.texture_fade == pytest.approx(expected)
