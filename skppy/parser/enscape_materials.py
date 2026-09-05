# SPDX-License-Identifier: MIT
"""Decode Enscape PBR metadata embedded in SketchUp materials."""

from __future__ import annotations

import math
import logging
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable
from dataclasses import replace

from ..data_structure.images import Texture
from ..data_structure.materials import Color, Material
from ..data_structure.model_metadata import AttributeDictionary

logger = logging.getLogger(__name__)


def apply_enscape_attributes(
    material: Material,
    dictionaries: Iterable[AttributeDictionary],
    *,
    parse_xml: Callable[[bytes], ET.Element],
    resolve_texture: Callable[[str, float, bool], Texture],
) -> bool:
    """Apply Enscape metadata retained in legacy material attribute dictionaries."""
    encoded = next(
        (
            entry.string_value
            for dictionary in dictionaries
            if dictionary.name == "Enscape.Material"
            for entry in dictionary.entries
            if entry.key == "MaterialData" and entry.value_type == 3
        ),
        "",
    )
    return _apply_metadata(material, encoded, parse_xml=parse_xml, resolve_texture=resolve_texture)


def apply_enscape_xml(
    material: Material,
    material_element: ET.Element,
    *,
    parse_xml: Callable[[bytes], ET.Element],
    resolve_texture: Callable[[str, float, bool], Texture],
) -> bool:
    """Apply an ``Enscape.Material`` dictionary and report whether it was valid."""
    encoded = _attribute_value(material_element, "Enscape.Material", "MaterialData")
    return _apply_metadata(material, encoded, parse_xml=parse_xml, resolve_texture=resolve_texture)


def _apply_metadata(
    material: Material,
    encoded: str,
    *,
    parse_xml: Callable[[bytes], ET.Element],
    resolve_texture: Callable[[str, float, bool], Texture],
) -> bool:
    if not encoded:
        return False
    try:
        root = parse_xml(encoded.strip().lstrip("\ufeff").encode("utf-8"))
    except (ET.ParseError, UnicodeError, ValueError):
        return False
    if _local_name(root.tag) != "SketchupMaterial":
        return False

    material.color = _hex_color(_text(root, "DiffuseColor")) or material.color
    material.tint_color = _hex_color(_text(root, "TintColor")) or material.tint_color
    material.texture_fade = _factor(_float(root, "ImageFade", material.texture_fade))
    material.alpha = _factor(_float(root, "Opacity", material.alpha))
    material.metallic = _factor(_float(root, "Metallic", material.metallic))
    material.roughness = _factor(_float(root, "Roughness", material.roughness))
    material.specular = _factor(_float(root, "Specular", material.specular))
    ior = _float(root, "IndexOfRefraction", material.ior)
    if ior > 0.0:
        material.ior = ior
    material.emission_color = _hex_color(_text(root, "EmissiveColor")) or material.emission_color
    material.emission_strength = max(0.0, _float(root, "EmissiveStrength", material.emission_strength))
    material.bump_strength = _float(root, "BumpAmount", material.bump_strength)
    material.normal_scale = max(0.0, _float(root, "NormalMapIntensity", material.normal_scale))
    if (_text(root, "TypeV5") or _text(root, "Type")) == "GLASS":
        material.transmission = 1.0 - material.alpha
        # Enscape glass opacity controls transmission, not surface coverage.
        # Keeping alpha at zero would also remove its reflections in Blender.
        material.alpha = 1.0

    sketchup_texture = material.texture
    diffuse_texture = _texture(root, "DiffuseTexture", resolve_texture, sketchup_texture=sketchup_texture)
    # Keep the embedded SketchUp image when an external Enscape replacement is
    # unavailable. Never replace usable pixels with a missing file reference.
    if diffuse_texture is not None and diffuse_texture.data is not None:
        material.texture = diffuse_texture
        material.has_texture = True
    relief_type = _text(root, "BumpMapType").upper()
    material.roughness_texture = _texture(root, "RoughnessTexture", resolve_texture, sketchup_texture=sketchup_texture)
    relief_texture = _texture(root, "BumpTexture", resolve_texture, sketchup_texture=sketchup_texture)
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
    *,
    sketchup_texture: Texture | None = None,
) -> Texture | None:
    element = _child(root, element_name)
    if element is None:
        return None
    brightness = max(0.0, _float(element, "Brightness", 1.0))
    inverted = _text(element, "IsInverted").lower() == "true"
    if _text(element, "Source") == "SKETCHUP":
        # The host image is authoritative even when Filepath retains an older
        # image name. Never look up that stale name in another material folder.
        texture = replace(sketchup_texture, brightness=brightness, inverted=inverted) if sketchup_texture else None
        return _apply_texture_size(texture, element)
    filename = _text(element, "Filepath")
    if not filename:
        return None
    return _apply_texture_size(resolve_texture(filename, brightness, inverted), element)


def _apply_texture_size(texture: Texture | None, element: ET.Element) -> Texture | None:
    """Convert observed meter tile sizes without changing the shared mesh UV basis."""
    if texture is None or _text(element, "UseExplicitTransformation").lower() != "true":
        return texture
    width = _float(element, "Width", 0.0)
    height = _float(element, "Height", 0.0)
    if width <= 1e-12 or height <= 1e-12:
        logger.warning("Invalid Enscape texture size for %r; retaining SketchUp mapping", texture.filename)
        return texture
    texture.uv_scale = (texture.x_scale * 0.0254 / width, texture.y_scale * 0.0254 / height)
    if _float(element, "Rotation", 0.0) != 0.0:
        logger.warning("Enscape texture rotation is not yet supported for %r", texture.filename)
    return texture


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
