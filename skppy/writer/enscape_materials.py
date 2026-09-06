# SPDX-License-Identifier: MIT
"""Export the observed Enscape scalar-material XML without mutating the input."""

from __future__ import annotations

from copy import copy
from dataclasses import replace
import math
import xml.etree.ElementTree as ET

from ..data_structure.materials import Color, Material
from ..data_structure.model import Model
from ..data_structure.model_metadata import AttributeDictionary, AttributeDictionaryEntry

_RESET_FIELDS = (
    "specular",
    "ior",
    "emission_color",
    "emission_strength",
    "bump_strength",
    "normal_scale",
    "tint_color",
    "texture_fade",
    "transmission",
)


def enscape_material_xml(material: Material) -> str:
    """Encode observed scalar layouts and a host-derived diffuse texture.

    Auxiliary maps, independent coverage plus transmission, and shader UV
    transforms are rejected until their export resource contract is verified.
    """
    _validate(material)
    # Compatibility samples establish self illumination in v4, and glass in v5.
    is_emissive = material.emission_strength > 0
    root = ET.Element("SketchupMaterial", {"Version": "4" if is_emissive else "5"})
    values = {
        "Type": "SELF_ILLUMINATED" if is_emissive else "GENERIC",
        **({} if is_emissive else {"TypeV5": "GLASS" if material.transmission else "GENERIC"}),
        "Opacity": _number(1 - material.transmission if material.transmission else material.alpha),
        "DiffuseColor": _color(material.color),
        "ImageFade": _number(material.texture_fade),
        "EmissiveColor": _color(material.emission_color),
        "EmissiveStrength": _number(material.emission_strength),
        "TintColor": _color(material.tint_color),
        "Roughness": _number(material.roughness),
        "BumpAmount": _number(material.bump_strength),
        "NormalMapIntensity": _number(material.normal_scale),
        "Metallic": _number(material.metallic),
        "Specular": _number(material.specular),
        "IndexOfRefraction": _number(material.ior),
        "IsSolidGlass": "false",
        "BumpMapType": "UNDEFINED",
        "TextureWidth": "0",
        "TextureHeight": "0",
    }
    for key, value in values.items():
        ET.SubElement(root, key).text = value
    if material.texture is not None:
        texture = material.texture
        element = ET.SubElement(root, "DiffuseTexture")
        texture_values = {
            "Source": "SKETCHUP",
            "Filepath": texture.filename.replace("\\", "/").split("/")[-1],
            "Brightness": _number(texture.brightness),
            "IsInverted": str(texture.inverted).lower(),
            "UseExplicitTransformation": "false",
            "Width": _number(abs(texture.x_scale) * 0.0254),
            "Height": _number(abs(texture.y_scale) * 0.0254),
            "Rotation": "0",
        }
        for key, value in texture_values.items():
            ET.SubElement(element, key).text = value
    return ET.tostring(root, encoding="unicode")


def prepare_enscape_export(model: Model, *, export_vray_materials: bool) -> tuple[Model, dict[int, str]]:
    """Copy only affected materials/attributes and keep the geometry shared read-only."""
    if export_vray_materials:
        raise ValueError("Choose either Enscape or V-Ray material export, not both")
    prepared = copy(model)
    prepared.materials = []
    prepared.attribute_dictionaries_by_object_id = dict(model.attribute_dictionaries_by_object_id)
    material_data = {}
    defaults = Material()
    for material in model.materials:
        encoded = enscape_material_xml(material)
        material_data[material.id] = encoded
        dictionaries = model.attribute_dictionaries_by_object_id.get(material.id, ())
        retained = [dictionary for dictionary in dictionaries if dictionary.name != "Enscape.Material"]
        prepared.attribute_dictionaries_by_object_id[material.id] = [
            *retained,
            AttributeDictionary(
                name="Enscape.Material",
                entries=[
                    AttributeDictionaryEntry(key="MaterialData", value_type=3, string_value=encoded),
                ],
            ),
        ]
        fallback = replace(material, **{name: getattr(defaults, name) for name in _RESET_FIELDS})
        if material.transmission:
            fallback.alpha = 1 - material.transmission
        if material.texture is not None:
            fallback.texture = replace(material.texture, brightness=1.0, inverted=False)
        prepared.materials.append(fallback)
    return prepared, material_data


def append_enscape_xml(material_element: ET.Element, material_data: str) -> None:
    """Add the Enscape dictionary to a writer-authored canonical material document."""
    namespace = "http://sketchup.google.com/schemas/1.0/types"
    container = ET.SubElement(material_element, "n0:AttributeDictionaries", {"xmlns:n0": namespace, "count": "1"})
    element = ET.SubElement(container, "n0:AttributeDictionary", {"name": "Enscape.Material", "count": "1"})
    ET.SubElement(element, "n0:Attribute", {"key": "MaterialData", "type": "10"}).text = material_data


def _validate(material: Material) -> None:
    for name in (
        "metallic_texture",
        "roughness_texture",
        "normal_texture",
        "bump_texture",
        "displacement_texture",
        "opacity_texture",
    ):
        if getattr(material, name) is not None:
            raise ValueError(f"Enscape export does not yet support {name}")
    if material.bump_map_type != "NONE" or material.displacement_scale != 0:
        raise ValueError("Enscape relief export requires a verified auxiliary-map resource layout")
    if material.transmission and material.alpha != 1:
        raise ValueError("Enscape export cannot combine independent alpha and transmission")
    if material.transmission and material.emission_strength:
        raise ValueError("Enscape export cannot combine glass and self illumination")
    _validate_factors(material)
    if material.texture is None:
        return
    if material.texture.uv_scale != (1, 1):
        raise ValueError("Enscape export does not yet support texture.uv_scale")
    brightness = material.texture.brightness
    if not math.isfinite(brightness) or brightness < 0:
        raise ValueError("Enscape texture brightness must be finite and nonnegative")


def _validate_factors(material: Material) -> None:
    for name in ("tint_color", "emission_color"):
        if getattr(material, name).a != 255:
            raise ValueError(f"Enscape {name} does not support an alpha channel")
    for name in ("alpha", "metallic", "roughness", "specular", "texture_fade", "transmission"):
        value = getattr(material, name)
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"Enscape {name} must be finite and within [0, 1]")
    for name in ("emission_strength", "normal_scale", "ior"):
        value = getattr(material, name)
        if not math.isfinite(value) or value < 0 or (name == "ior" and value == 0):
            raise ValueError(f"Invalid Enscape {name}: {value}")
    if not math.isfinite(material.bump_strength):
        raise ValueError("Enscape bump_strength must be finite")


def _color(color: Color) -> str:
    if any(not isinstance(channel, int) or not 0 <= channel <= 255 for channel in (color.r, color.g, color.b)):
        raise ValueError("Enscape color channels must be integers in [0, 255]")
    return f"#{color.r:02X}{color.g:02X}{color.b:02X}"


def _number(value: float) -> str:
    return format(value, ".17g")
