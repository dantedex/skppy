# SPDX-License-Identifier: MIT
"""Recognize diffuse image adjustments whose Enscape representation is established."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math
from typing import Any

from . import skppy


@dataclass(frozen=True)
class DiffuseImage:
    """An image node plus color adjustments, separate from its unmodified alpha."""

    node: Any
    brightness: float = 1.0
    inverted: bool = False


def read_diffuse(
    socket: Any,
    material: skppy.Material,
    color: Callable[[Any], skppy.Color],
) -> DiffuseImage | None:
    """Read image -> invert -> multiply -> fade, rejecting other graph layouts."""
    if not socket.is_linked:
        return None
    node = _color_node(socket)
    if node.type == "MIX_RGB" and node.blend_type == "MIX":
        _validate_mix(node)
        if node.inputs[1].is_linked:
            raise ValueError("Enscape image fade requires a constant base color")
        material.texture_fade = float(node.inputs[0].default_value)
        material.color = color(node.inputs[1].default_value)
        node = _color_node(node.inputs[2])

    node, brightness, tint = _read_multipliers(node)
    material.tint_color = color(tint)

    inverted = node.type == "INVERT"
    if inverted:
        if node.mute or node.inputs["Fac"].is_linked or node.inputs["Fac"].default_value != 1:
            raise ValueError("Enscape inversion requires an unmuted full-strength invert node")
        node = _color_node(node.inputs["Color"])
    if node.type != "TEX_IMAGE" or node.mute or node.image is None:
        raise ValueError(
            "Enscape export requires a base image with supported tint, brightness, inversion and fade nodes"
        )
    return DiffuseImage(node, brightness, inverted)


def _read_multipliers(node: Any) -> tuple[Any, float, list[float]]:
    brightness = 1.0
    tint = [1.0, 1.0, 1.0]
    # Two stages cover imported tint and brightness, and bound traversal of user graphs.
    for _ in range(2):
        if node.type != "MIX_RGB" or node.blend_type != "MULTIPLY":
            break
        _validate_mix(node)
        if node.inputs[0].default_value != 1 or node.inputs[2].is_linked:
            raise ValueError("Enscape color multiplication requires factor 1 and a constant multiplier")
        values = tuple(node.inputs[2].default_value[:3])
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise ValueError("Enscape color multipliers must be finite and nonnegative")
        if values[0] == values[1] == values[2]:
            brightness *= values[0]
        else:
            if max(values) > 1:
                raise ValueError("Enscape tint multipliers must be within [0, 1]")
            tint = [current * value for current, value in zip(tint, values)]
        node = _color_node(node.inputs[1])
    return node, brightness, tint


def _color_node(socket: Any) -> Any:
    if not socket.is_linked or socket.links[0].from_socket.name != "Color":
        raise ValueError("Enscape diffuse adjustments require a linked Color output")
    return socket.links[0].from_node


def _validate_mix(node: Any) -> None:
    if node.mute or node.use_clamp or node.use_alpha or node.inputs[0].is_linked:
        raise ValueError("Enscape diffuse mixing requires an unmuted, unclamped node with a constant factor")
    factor = node.inputs[0].default_value
    if not math.isfinite(factor) or not 0 <= factor <= 1:
        raise ValueError("Enscape diffuse mix factors must be finite and within [0, 1]")
