# SPDX-License-Identifier: MIT
"""Extract the verified Enscape subset from Blender's active surface shader."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import math
from typing import Any

import numpy as np

from . import skppy
from .enscape_diffuse import DiffuseImage, read_diffuse


def populate_material(source: Any, target: skppy.Material, channel: Callable[[float], int]) -> DiffuseImage | None:
    """Copy supported appearance into *target*; reject unrepresented shader state."""
    if not source.use_nodes or source.node_tree is None:
        target.color = _color(source.diffuse_color, channel)
        target.alpha = float(source.diffuse_color[3])
        target.metallic = float(source.metallic)
        target.roughness = float(source.roughness)
        return None
    bsdf = _active_principled(source)
    _validate_shader(bsdf)
    target.color = _color(bsdf.inputs["Base Color"].default_value, channel)
    target.alpha = float(bsdf.inputs["Alpha"].default_value)
    target.metallic = float(bsdf.inputs["Metallic"].default_value)
    target.roughness = float(bsdf.inputs["Roughness"].default_value)
    target.ior = float(bsdf.inputs["IOR"].default_value)
    target.specular = float(bsdf.inputs["Specular IOR Level"].default_value)
    target.transmission = float(bsdf.inputs["Transmission Weight"].default_value)
    target.emission_strength = float(bsdf.inputs["Emission Strength"].default_value)
    target.emission_color = _color(bsdf.inputs["Emission Color"].default_value, channel)
    diffuse = read_diffuse(bsdf.inputs["Base Color"], target, lambda values: _color(values, channel))
    if diffuse is not None:
        _validate_image(diffuse.node)
        diffuse = replace(diffuse, uv_scale=_image_uv_scale(diffuse.node))
    _read_alpha(bsdf.inputs["Alpha"], diffuse.node if diffuse is not None else None, target)
    return diffuse


def _color(values: Any, channel: Callable[[float], int]) -> skppy.Color:
    if any(not math.isfinite(value) or not 0 <= value <= 1 for value in values[:3]):
        raise ValueError(
            "Enscape export requires finite RGB colors within [0, 1]; use emission strength for HDR intensity"
        )
    return skppy.Color(*(channel(value) for value in values[:3]))


def _active_principled(material: Any) -> Any:
    outputs = [node for node in material.node_tree.nodes if node.type == "OUTPUT_MATERIAL" and node.is_active_output]
    if len(outputs) != 1:
        raise ValueError("Enscape export requires one active material output")
    output = outputs[0]
    if output.inputs["Volume"].is_linked or output.inputs["Displacement"].is_linked:
        raise ValueError("Enscape export does not support volume or displacement graphs")
    surface = output.inputs["Surface"]
    if not surface.is_linked or surface.links[0].from_node.type != "BSDF_PRINCIPLED":
        raise ValueError("Enscape export requires a direct Principled BSDF surface")
    bsdf = surface.links[0].from_node
    if bsdf.mute:
        raise ValueError("Enscape export does not support a muted surface shader")
    return bsdf


def _validate_shader(bsdf: Any) -> None:
    for socket in bsdf.inputs:
        if socket.is_linked and socket.name not in {"Base Color", "Alpha"}:
            raise ValueError(f"Enscape export does not support a linked {socket.name} input")
    for name in (
        "Subsurface Weight",
        "Coat Weight",
        "Sheen Weight",
        "Anisotropic",
        "Thin Film Thickness",
        "Diffuse Roughness",
        "Thin Wall",
    ):
        socket = bsdf.inputs.get(name)
        if socket is not None and socket.default_value != 0:
            raise ValueError(f"Enscape export does not support {name}")
    tint = bsdf.inputs.get("Specular Tint")
    if tint is not None and tuple(tint.default_value[:3]) != (1, 1, 1):
        raise ValueError("Enscape export does not support Specular Tint")


def _validate_image(node: Any) -> None:
    if node.image.source not in {"FILE", "GENERATED"} or node.image.colorspace_settings.name != "sRGB":
        raise ValueError("Enscape export requires a static sRGB base-color image")
    if node.projection != "FLAT" or node.extension != "REPEAT":
        raise ValueError("Enscape export requires flat, repeating image mapping")
    if node.interpolation != "Linear":
        raise ValueError("Enscape export requires linear image interpolation")


def _image_uv_scale(image_node: Any) -> tuple[float, float]:
    vector = image_node.inputs["Vector"]
    if not vector.is_linked:
        return (1.0, 1.0)
    link = vector.links[0]
    node = link.from_node
    if node.type in {"VECT_MATH", "MAPPING"} and link.from_socket.name != "Vector":
        raise ValueError("Enscape UV mapping requires a Vector output")
    scale = (1.0, 1.0, 1.0)
    if node.type == "VECT_MATH" and node.operation == "MULTIPLY":
        if node.mute or node.inputs[1].is_linked:
            raise ValueError("Enscape UV multiplication requires an unmuted node and a constant multiplier")
        scale = tuple(node.inputs[1].default_value)
        vector = node.inputs[0]
    elif node.type == "MAPPING":
        scale = _mapping_scale(node)
        vector = node.inputs["Vector"]
    if not vector.is_linked:
        raise ValueError("Enscape export requires a linked active UV source")
    source = vector.links[0]
    if not _is_active_uv(source):
        raise ValueError("Enscape export requires the active UV mapping with at most one supported scale node")
    if any(not math.isfinite(value) or value <= 0 for value in scale) or scale[2] != 1:
        raise ValueError("Enscape UV scale must be finite and positive, with Z equal to 1")
    return (scale[0], scale[1])


def _is_active_uv(link: Any) -> bool:
    node = link.from_node
    if node.mute or link.from_socket.name != "UV" or getattr(node, "from_instancer", False):
        return False
    return node.type == "TEX_COORD" or (node.type == "UVMAP" and not node.uv_map)


def _mapping_scale(node: Any) -> tuple[float, float, float]:
    if node.mute or node.vector_type != "POINT":
        raise ValueError("Enscape export requires an unmuted Point mapping node")
    for name in ("Location", "Rotation", "Scale"):
        if node.inputs[name].is_linked:
            raise ValueError(f"Enscape export requires constant mapping {name}")
    if any(node.inputs[name].default_value[index] != 0 for name in ("Location", "Rotation") for index in range(3)):
        raise ValueError("Enscape export does not yet support mapping translation or rotation")
    return tuple(node.inputs["Scale"].default_value)


def _read_alpha(socket: Any, image_node: Any | None, material: skppy.Material) -> None:
    if not socket.is_linked:
        if image_node is not None and _has_transparent_pixels(image_node.image):
            raise ValueError(
                "Enscape export requires the base image alpha to be connected when its pixels are transparent"
            )
        return
    link = socket.links[0]
    material.alpha = 1.0
    # The importer uses image alpha multiplied by the material's scalar opacity.
    if link.from_node.type == "MATH" and link.from_node.operation == "MULTIPLY" and not link.from_node.mute:
        multiply = link.from_node
        if not multiply.inputs[0].is_linked or multiply.inputs[1].is_linked or multiply.use_clamp:
            raise ValueError("Enscape export requires image alpha multiplied by a constant")
        material.alpha = float(multiply.inputs[1].default_value)
        link = multiply.inputs[0].links[0]
    if image_node is None or link.from_node != image_node or link.from_socket.name != "Alpha":
        raise ValueError("Enscape export supports only the base image alpha, optionally multiplied by a constant")


def _has_transparent_pixels(image: Any) -> bool:
    # Blender 4.5 RNA arrays do not support stepped slices; bulk reads work in both LTS versions.
    pixels = np.empty(len(image.pixels), dtype=np.float32)
    image.pixels.foreach_get(pixels)
    return bool(np.any(pixels[3::4] < 1))
