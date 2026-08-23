# SPDX-License-Identifier: MIT
"""Decode V-Ray material graphs stored in SketchUp attribute dictionaries."""

from __future__ import annotations

import json
import math
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping
from typing import Any

from ..data_structure.materials import Color, Material
from ..data_structure.model import Model
from ..data_structure.model_metadata import AttributeDictionary

_COLOR_PATTERN = re.compile(
    r"^Color\(\s*([^,]+)\s*,\s*([^,]+)\s*,\s*([^\)]+)\s*\)$",
)
_WRAPPER_REFERENCES = {
    "BRDFBump": "base_brdf",
    "MtlMaterialID": "base_mtl",
    "MtlRenderStats": "base_mtl",
    "MtlSingleBRDF": "brdf",
}


def apply_vray_materials(model: Model) -> None:
    """Apply V-Ray PBR values from legacy model-object attributes."""
    for material in model.materials:
        apply_vray_attribute_dictionaries(
            material,
            model.attribute_dictionaries_by_object_id.get(material.id, ()),
        )


def apply_vray_attribute_dictionaries(
    material: Material,
    dictionaries: Iterable[AttributeDictionary],
) -> bool:
    """Apply one material's V-Ray dictionaries and report whether a graph was found."""
    values = {
        dictionary.name: {entry.key: entry.string_value for entry in dictionary.entries}
        for dictionary in dictionaries
        if dictionary.name in {"VRayInfo", "VRayPlugins"}
    }
    return _apply_vray_values(material, values.get("VRayInfo", {}), values.get("VRayPlugins", {}))


def apply_vray_xml(material: Material, material_element: ET.Element) -> bool:
    """Apply V-Ray PBR values embedded in a modern ``material.xml`` element."""
    dictionaries: dict[str, dict[str, str]] = {}
    for element in material_element.iter():
        if _local_name(element.tag) != "AttributeDictionary":
            continue
        name = element.get("name", "")
        if name not in {"VRayInfo", "VRayPlugins"}:
            continue
        dictionaries[name] = {
            child.get("key", ""): (child.text or "").strip().lstrip("\ufeff")
            for child in element
            if _local_name(child.tag) == "Attribute"
        }
    return _apply_vray_values(
        material,
        dictionaries.get("VRayInfo", {}),
        dictionaries.get("VRayPlugins", {}),
    )


def _apply_vray_values(material: Material, info: Mapping[str, str], encoded_plugins: Mapping[str, str]) -> bool:
    plugins = _decode_plugins(encoded_plugins.values())
    brdf = _find_material_brdf(info.get("main_plugin", ""), plugins)
    if brdf is None:
        return False
    params = _mapping(brdf.get("params"))
    user_data = _mapping(brdf.get("userData"))
    if material.metallic_texture is None or _is_scalar(params.get("metalness")):
        material.metallic = _factor(_parameter_float(params, user_data, "metalness", material.metallic))
    if material.roughness_texture is None or _is_scalar(params.get("reflect_glossiness")):
        glossiness = _parameter_float(params, user_data, "reflect_glossiness", 1.0 - material.roughness)
        use_roughness = _parameter_bool(params.get("option_use_roughness"))
        material.roughness = _factor(glossiness if use_roughness else 1.0 - glossiness)
    ior = _parameter_float(params, user_data, "fresnel_ior", material.ior)
    if ior > 0.0:
        material.ior = ior
    diffuse = _color(params.get("diffuse"))
    if diffuse is not None:
        material.color = diffuse
    return True


def _decode_plugins(values: Iterable[str]) -> dict[str, dict[str, Any]]:
    plugins: dict[str, dict[str, Any]] = {}
    for value in values:
        try:
            decoded = json.loads(value.lstrip("\ufeff"))
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(decoded, dict) and isinstance(decoded.get("name"), str):
            plugins[decoded["name"]] = decoded
    return plugins


def _find_material_brdf(main_plugin: str, plugins: Mapping[str, dict[str, Any]]) -> dict[str, Any] | None:
    candidates = []
    if main_plugin:
        candidates.append(main_plugin)
    candidates.extend(name for name, plugin in plugins.items() if plugin.get("class") == "MtlSingleBRDF")
    for candidate in candidates:
        resolved = _resolve_brdf(candidate, plugins, set())
        if resolved is not None:
            return resolved
    direct = [plugin for plugin in plugins.values() if plugin.get("class") == "BRDFVRayMtl"]
    return direct[0] if len(direct) == 1 else None


def _resolve_brdf(
    reference: str,
    plugins: Mapping[str, dict[str, Any]],
    visited: set[str],
) -> dict[str, Any] | None:
    if not reference or reference in visited:
        return None
    plugin = plugins.get(reference)
    if plugin is None:
        return None
    visited = {*visited, reference}
    class_name = plugin.get("class")
    if class_name == "BRDFVRayMtl":
        return plugin
    params = _mapping(plugin.get("params"))
    wrapper_key = _WRAPPER_REFERENCES.get(str(class_name))
    if wrapper_key is not None:
        return _resolve_brdf(str(params.get(wrapper_key, "")), plugins, visited)
    if class_name == "BRDFLayered":
        for child in _list_references(params.get("brdfs")):
            resolved = _resolve_brdf(child, plugins, visited)
            if resolved is not None:
                return resolved
    return None


def _list_references(value: object) -> list[str]:
    if not isinstance(value, str) or not value.startswith("List(") or not value.endswith(")"):
        return []
    return [part.strip() for part in value[5:-1].split(",") if part.strip()]


def _parameter_float(params: Mapping[str, Any], user_data: Mapping[str, Any], name: str, default: float) -> float:
    for value in (params.get(name), user_data.get(f"{name}_float")):
        try:
            result = float(str(value))
        except (TypeError, ValueError):
            continue
        if math.isfinite(result):
            return result
    return default


def _parameter_bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _is_scalar(value: object) -> bool:
    try:
        return math.isfinite(float(str(value)))
    except (TypeError, ValueError):
        return False


def _factor(value: float) -> float:
    return min(max(value, 0.0), 1.0)


def _color(value: object) -> Color | None:
    if not isinstance(value, str) or (match := _COLOR_PATTERN.match(value)) is None:
        return None
    try:
        linear = tuple(_factor(float(component)) for component in match.groups())
    except ValueError:
        return None
    red, green, blue = (_linear_to_byte(component) for component in linear)
    return Color(red, green, blue)


def _linear_to_byte(value: float) -> int:
    srgb = 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1.0 / 2.4) - 0.055
    return round(_factor(srgb) * 255.0)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, dict) else {}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
