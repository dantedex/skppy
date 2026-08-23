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


@pytest.mark.parametrize("emission_color", ["#123", "#GG0000"])
def test_safely_defaults_invalid_enscape_fields(emission_color: str) -> None:
    metadata = f"""<SketchupMaterial>
      <Metallic>nan</Metallic><Roughness>bad</Roughness><Specular>2</Specular>
      <IndexOfRefraction>0</IndexOfRefraction><EmissiveColor>{emission_color}</EmissiveColor>
      <BumpAmount>-2</BumpAmount><NormalMapIntensity>-3</NormalMapIntensity><BumpMapType>BUMP</BumpMapType>
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
    assert (material.emission_strength, material.bump_strength, material.normal_scale) == pytest.approx((0, 0, 0))
    assert material.bump_map_type == "BUMP"
    assert material.bump_texture is None
    assert material.roughness_texture is None
