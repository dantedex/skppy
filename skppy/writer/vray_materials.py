# SPDX-License-Identifier: MIT
"""Deterministic V-Ray material metadata generation."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Literal

from ..data_structure.materials import Material
from ..data_structure.model_metadata import AttributeDictionary, AttributeDictionaryEntry

VrayTarget = Literal["modern", "sketchup_2017"]

_VRAY_DICTIONARY_NAMES = frozenset({"VRayInfo", "VRayPlugins"})
_VRAY_TYPES_NAMESPACE = "http://sketchup.google.com/schemas/1.0/types"
_TARGET_VERSIONS: dict[VrayTarget, tuple[int, int]] = {
    "modern": (72002, 23),
    "sketchup_2017": (42003, 16),
}


def vray_material_dictionaries(material: Material, *, target: VrayTarget) -> list[AttributeDictionary]:
    """Build the V-Ray dictionaries representing one material's PBR appearance."""
    try:
        info_version, plugin_version = _TARGET_VERSIONS[target]
    except KeyError as exc:
        raise ValueError(f"Unsupported V-Ray material target: {target!r}") from exc

    main_plugin = f"/{material.name}"
    brdf_plugin = f"{main_plugin}/VRay Mtl"
    texture_plugin = f"{brdf_plugin}/Bitmap" if material.texture is not None else None
    wrapper = {
        "name": main_plugin,
        "class": "MtlSingleBRDF",
        "type": "material",
        "version": plugin_version,
        "params": {
            "scene_name": _scene_name(material.name, target),
            "filter": "Color(1,1,1)",
            "brdf": brdf_plugin,
            "double_sided": "1",
            "allow_negative_colors": "0",
            **({"channels": "List()"} if target == "modern" else {}),
        },
        "userData": {
            "materialID": "",
            "swatch_type": "generic",
            "effected_by_mtl_override": "1",
            "displacement": "",
            "bind_texture_on": "1",
            "bind_texture_mode": "4",
            "bind_opacity_on": "1",
            "bump": "",
            "bind_all_on": "1" if texture_plugin is not None else "0",
            "bind_color_on": "1",
            "viewport_texture": "",
            "renderStats": "",
            **({"ui_tags": "List()"} if target == "modern" else {}),
        },
    }
    diffuse = _linear_color(material)
    metallic = _format_factor(material.metallic)
    roughness = _format_factor(material.roughness)
    opacity = _format_factor(material.alpha)
    brdf = {
        "name": brdf_plugin,
        "class": "BRDFVRayMtl",
        "type": "BRDF",
        "version": plugin_version,
        "params": {
            "diffuse": texture_plugin or diffuse,
            "metalness": metallic,
            "option_use_roughness": "1",
            "reflect_glossiness": roughness,
            "opacity": opacity,
            "opacity_color": f"AColor({opacity},{opacity},{opacity},{opacity})",
            "opacity_mode": "2",
            "option_double_sided": "1",
        },
        "userData": {
            "diffuse_color": diffuse,
            "diffuse_tex": texture_plugin or "",
            "diffuse_tex_mult": "1",
            "metalness_float": metallic,
            "reflect_glossiness_float": roughness,
            "opacity_float": opacity,
            "diffuse_tex_on": "1" if texture_plugin is not None else "0",
            "metalness_tex_on": "0",
            "reflect_glossiness_tex_on": "0",
            "opacity_tex_on": "0",
            "linear_workflow": "1",
            "texture_multiplier_mode": "1",
        },
    }
    plugins = [wrapper, brdf]
    if texture_plugin is not None:
        plugins.extend(_texture_plugins(material, texture_plugin, target=target, plugin_version=plugin_version))
    return [
        AttributeDictionary(
            name="VRayInfo",
            entries=[
                _string_entry("class", "MtlSingleBRDF"),
                _string_entry("main_plugin", main_plugin),
                _string_entry("type", "material"),
                AttributeDictionaryEntry(key="version", value_type=0, int_value=info_version),
            ],
        ),
        AttributeDictionary(
            name="VRayPlugins",
            entries=[_string_entry(str(plugin["name"]), _encode_plugin(plugin)) for plugin in plugins],
        ),
    ]


def replace_vray_dictionaries(
    dictionaries: Iterable[AttributeDictionary],
    material: Material,
    *,
    target: VrayTarget,
) -> list[AttributeDictionary]:
    """Replace V-Ray-owned dictionaries while preserving unrelated metadata."""
    retained = [dictionary for dictionary in dictionaries if dictionary.name not in _VRAY_DICTIONARY_NAMES]
    return [*retained, *vray_material_dictionaries(material, target=target)]


def append_vray_xml(material_element: ET.Element, material: Material) -> None:
    """Append modern V-Ray dictionaries to a material XML element."""
    material_element.set("xmlns:n0", _VRAY_TYPES_NAMESPACE)
    dictionaries = vray_material_dictionaries(material, target="modern")
    container = ET.SubElement(material_element, "n0:AttributeDictionaries", {"count": str(len(dictionaries))})
    for dictionary in dictionaries:
        dictionary_element = ET.SubElement(
            container,
            "n0:AttributeDictionary",
            {"name": dictionary.name, "count": str(len(dictionary.entries))},
        )
        for entry in dictionary.entries:
            value, xml_type = _xml_entry_value(entry)
            ET.SubElement(dictionary_element, "n0:Attribute", {"key": entry.key, "type": xml_type}).text = value


def _scene_name(material_name: str, target: VrayTarget) -> str:
    return f"List({material_name})" if target == "modern" else f"ListString({material_name})"


def _texture_plugins(
    material: Material,
    texture_plugin: str,
    *,
    target: VrayTarget,
    plugin_version: int,
) -> list[dict[str, object]]:
    """Return the observed bitmap and channel plugins for one embedded base-colour image."""
    assert material.texture is not None
    bitmap_plugin = f"{texture_plugin}/Bitmap"
    uvw_plugin = f"{texture_plugin}/UVW"
    texture = {
        "name": texture_plugin,
        "class": "TexBitmap",
        "type": "texture",
        "version": plugin_version,
        "params": {
            "w": "1",
            "un_noise_phase": "0",
            "tile": "1",
            "placement_type": "0",
            "uv_noise_levels": "1",
            "uv_noise_amount": "10",
            "nouvw_color": "Color(0.5,0.5,0.5)",
            "invert": "0",
            "uv_noise_on": "0",
            "u": "0",
            "uvwgen": uvw_plugin,
            "color_offset": "Color(0,0,0)",
            "tile_u": "0",
            "tile_v": "0",
            "v": "0",
            "alpha_mult": "1",
            "invert_alpha": "0",
            "uv_noise_size": "1",
            "alpha_from_intensity": "0",
            "h": "1",
            "color_mult": "Color(1,1,1)",
            "bitmap": bitmap_plugin,
            "jitter": "0",
        },
        "userData": {
            "lock_w_h": "0",
            "swatch_type": "2d",
            "color_mult_color": "Color(1,1,1)",
            "color_mult_tex_on": "1",
            "color_offset_color": "Color(0,0,0)",
            "nouvw_color_color": "Color(0.5,0.5,0.5)",
            "texture_multiplier_mode": "1",
            **({"ui_tags": "List()"} if target == "modern" else {}),
        },
    }
    bitmap_params = {
        "use_data_window": "1",
        "load_file": "1",
        "gamma": "0.454545" if target == "modern" else "0.45454545",
        "interpolation": "0",
        "filter_blur": "1",
        "filter_type": "5",
        "allow_negative_colors": "0",
        "file": _texture_filename(material),
        "frame_number": "-2147483648",
    }
    if target == "modern":
        bitmap_params.update({"transfer_function": "2", "rgb_color_space": "raw"})
    else:
        bitmap_params["color_space"] = "2"
    bitmap = {
        "name": bitmap_plugin,
        "class": "BitmapBuffer",
        "type": "bitmap",
        "version": plugin_version,
        "params": bitmap_params,
        "userData": {"ui_tags": "List()"} if target == "modern" else {},
    }
    transform = (
        "Transform(Matrix(Vector(1,0,0),Vector(0,1,0),Vector(0,0,1)),Vector(0,0,0))"
        if target == "modern"
        else "Transform(Matrix(Vector(1, 0, 0), Vector(0, 1, 0), Vector(0, 0, 1)),Vector(0, 0, 0))"
    )
    uvw = {
        "name": uvw_plugin,
        "class": "UVWGenChannel",
        "type": "uvw",
        "version": plugin_version,
        "params": {
            "wrap_w": "0",
            "wrap_u": "0",
            "wrap_mode": "1",
            "uvwgen": "",
            "uvw_transform_tex": "",
            "uvw_transform": transform,
            "uvw_channel": "1",
            "use_double_sided_mode": "0",
            "tex_transform": transform,
            "crop_v": "0",
            "crop_u": "0",
            "wrap_v": "0",
            "duvw_scale": "1",
            "coverage": "Vector(1,1,1)",
            "crop_w": "0",
            "nsamples": "0",
        },
        "userData": {
            "rotation": "0",
            "lock_repeat": "0",
            **({"ui_tags": "List()"} if target == "modern" else {}),
        },
    }
    return [texture, bitmap, uvw]


def _linear_color(material: Material) -> str:
    channels = (_srgb_to_linear(channel / 255.0) for channel in (material.color.r, material.color.g, material.color.b))
    return f"Color({','.join(_format_factor(channel) for channel in channels)})"


def _srgb_to_linear(value: float) -> float:
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _format_factor(value: float) -> str:
    return format(value, ".17g")


def _texture_filename(material: Material) -> str:
    assert material.texture is not None
    return PurePosixPath(material.texture.filename.replace("\\", "/")).name


def _string_entry(key: str, value: str) -> AttributeDictionaryEntry:
    return AttributeDictionaryEntry(key=key, value_type=3, string_value=value)


def _encode_plugin(plugin: dict[str, object]) -> str:
    return json.dumps(plugin, ensure_ascii=False, separators=(",", ":"))


def _xml_entry_value(entry: AttributeDictionaryEntry) -> tuple[str, str]:
    if entry.value_type == 0:
        return str(entry.int_value), "4"
    if entry.value_type == 3:
        return entry.string_value, "10"
    raise ValueError(f"Unsupported V-Ray XML attribute value type: {entry.value_type}")
