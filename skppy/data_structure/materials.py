# SPDX-License-Identifier: MIT
"""
Material and texture data classes.

.. module:: skppy.data_structure.materials
   :synopsis: Material, color, and texture data structures

Materials define surface appearance (color, texture, PBR properties).
Textures are image files referenced by materials.

Example
-------
::

    color = Color(r=180, g=80, b=60, a=255)
    texture = Texture(filename="brick.jpg", x_scale=100.0, y_scale=100.0)
    mat = Material(id=1, name="Brick", color=color, texture=texture)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Optional

if TYPE_CHECKING:
    from .images import Texture


@dataclass(slots=True)
class Color:
    """
    RGBA color with components in the [0, 255] integer range.

    Parameters
    ----------
    r : int
        Red channel (0-255).
    g : int
        Green channel (0-255).
    b : int
        Blue channel (0-255).
    a : int, optional
        Alpha channel (0-255). Default 255 (fully opaque).

    Examples
    --------
    >>> Color(255, 0, 0)
    Color(r=255, g=0, b=0, a=255)
    >>> Color(200, 200, 200, 128)
    Color(r=200, g=200, b=200, a=128)
    """

    r: int
    g: int
    b: int
    a: int = 255


@dataclass(slots=True)
class Material:
    """
    A SketchUp material.

    Materials define the surface appearance of faces. They can have a
    base color, texture slots, and physically based rendering properties.

    Parameters
    ----------
    id : int
        Unique material ID.
    name : str
        Material name (unique within the document).
    color : Color
        Base diffuse color.
    alpha : float, optional
        Opacity (0.0 = fully transparent, 1.0 = fully opaque). Default 1.0.
    has_texture : bool, optional
        Whether a texture is present.
    texture : Texture or None, optional
        Texture data and scale.
    metallic : float, optional
        PBR metallic factor (0.0 to 1.0). Default 0.0.
    roughness : float, optional
        PBR roughness factor (0.0 to 1.0). Default 1.0.
    specular : float, optional
        Dielectric specular level (0.0 to 1.0). Default 0.5.
    ior : float, optional
        Index of refraction. Default 1.5.
    emission_color : Color, optional
        Emissive surface colour. Default black.
    emission_strength : float, optional
        Emissive intensity. Default 0.0.
    bump_map_type : str, optional
        Relief interpretation: ``NONE``, ``BUMP``, ``NORMAL``, or
        ``DISPLACEMENT``.
    bump_strength : float, optional
        Height/bump strength. Default 0.0.
    normal_scale : float, optional
        Tangent-space normal map strength. Default 1.0.
    displacement_scale : float, optional
        Displacement amount. Default 0.0.
    metallic_texture : Texture or None, optional
        Non-color metallic map.
    roughness_texture : Texture or None, optional
        Non-color roughness map.
    bump_texture : Texture or None, optional
        Grayscale height map used for bump shading.
    normal_texture : Texture or None, optional
        Tangent-space normal map.
    displacement_texture : Texture or None, optional
        Grayscale displacement/height map.

    Examples
    --------
    >>> mat = Material(id=1, name="Brick", color=Color(180, 80, 60))
    >>> mat.name
    'Brick'
    >>> mat2 = Material(id=2, name="Steel", color=Color(180, 180, 190),
    ...                 metallic=1.0, roughness=0.2)
    """

    id: int = 0
    name: str = ""
    color: Color = field(default_factory=lambda: Color(0, 0, 0))
    alpha: float = 1.0
    has_texture: bool = False
    texture: Optional["Texture"] = None
    metallic: float = 0.0
    roughness: float = 1.0
    specular: float = 0.5
    ior: float = 1.5
    emission_color: Color = field(default_factory=lambda: Color(0, 0, 0))
    emission_strength: float = 0.0
    bump_map_type: Literal["NONE", "BUMP", "NORMAL", "DISPLACEMENT"] = "NONE"
    bump_strength: float = 0.0
    normal_scale: float = 1.0
    displacement_scale: float = 0.0
    metallic_texture: Optional["Texture"] = None
    roughness_texture: Optional["Texture"] = None
    bump_texture: Optional["Texture"] = None
    normal_texture: Optional["Texture"] = None
    displacement_texture: Optional["Texture"] = None
