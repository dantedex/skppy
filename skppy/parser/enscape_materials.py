# SPDX-License-Identifier: MIT
"""Decode Enscape PBR metadata embedded in SketchUp materials."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from collections.abc import Callable

from ..data_structure.images import Texture
from ..data_structure.materials import Color, Material


def apply_enscape_xml(
    material: Material,
    material_element: ET.Element,
    *,
    parse_xml: Callable[[bytes], ET.Element],
    resolve_texture: Callable[[str, float, bool], Texture],
) -> bool:
    """Apply an ``Enscape.Material`` dictionary and report whether it was valid."""
    encoded = _attribute_value(material_element, "Enscape.Material", "MaterialData")
    if not encoded:
        return False
    try:
        root = parse_xml(encoded.lstrip("\ufeff").encode("utf-8"))
    except (ET.ParseError, UnicodeError, ValueError):
        return False
    if _local_name(root.tag) != "SketchupMaterial":
        return False

    material.metallic = _factor(_float(root, "Metallic", material.metallic))
    material.roughness = _factor(_float(root, "Roughness", material.roughness))
    material.specular = _factor(_float(root, "Specular", material.specular))
    ior = _float(root, "IndexOfRefraction", material.ior)
    if ior > 0.0:
        material.ior = ior
    material.emission_color = _hex_color(_text(root, "EmissiveColor")) or material.emission_color
    material.emission_strength = max(0.0, _float(root, "EmissiveStrength", material.emission_strength))
    material.bump_strength = max(0.0, _float(root, "BumpAmount", material.bump_strength))
    material.normal_scale = max(0.0, _float(root, "NormalMapIntensity", material.normal_scale))

    relief_type = _text(root, "BumpMapType").upper()
    material.roughness_texture = _texture(root, "RoughnessTexture", resolve_texture)
    relief_texture = _texture(root, "BumpTexture", resolve_texture)
    if relief_type == "BUMP":
        material.bump_map_type = "BUMP"
        material.bump_texture = relief_texture
    elif relief_type == "NORMAL":
        material.bump_map_type = "NORMAL"
        material.normal_texture = relief_texture
    elif relief_type == "DISPLACEMENT":
        material.bump_map_type = "DISPLACEMENT"
        material.displacement_texture = relief_texture
        material.displacement_scale = material.bump_strength
    else:
        material.bump_map_type = "NONE"
    return True


def _attribute_value(material_element: ET.Element, dictionary_name: str, key: str) -> str:
    for element in material_element.iter():
        if _local_name(element.tag) != "AttributeDictionary" or element.get("name") != dictionary_name:
            continue
        for child in element:
            if _local_name(child.tag) == "Attribute" and child.get("key") == key:
                return (child.text or "").strip()
    return ""


def _texture(
    root: ET.Element,
    element_name: str,
    resolve_texture: Callable[[str, float, bool], Texture],
) -> Texture | None:
    element = _child(root, element_name)
    if element is None:
        return None
    filename = _text(element, "Filepath")
    if not filename:
        return None
    brightness = max(0.0, _float(element, "Brightness", 1.0))
    inverted = _text(element, "IsInverted").lower() == "true"
    return resolve_texture(filename, brightness, inverted)


def _float(parent: ET.Element, name: str, default: float) -> float:
    try:
        value = float(_text(parent, name))
    except ValueError:
        return default
    return value if math.isfinite(value) else default


def _factor(value: float) -> float:
    return min(max(value, 0.0), 1.0)


def _hex_color(value: str) -> Color | None:
    normalized = value.lstrip("#")
    if len(normalized) not in {6, 8}:
        return None
    try:
        components = [int(normalized[index : index + 2], 16) for index in range(0, len(normalized), 2)]
    except ValueError:
        return None
    return Color(*components)


def _text(parent: ET.Element, name: str) -> str:
    child = _child(parent, name)
    return (child.text or "").strip() if child is not None else ""


def _child(parent: ET.Element, name: str) -> ET.Element | None:
    return next((child for child in parent if _local_name(child.tag) == name), None)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
