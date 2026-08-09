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
from typing import TYPE_CHECKING, Optional

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
    base color, an optional texture, and PBR properties (metallic, roughness).

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
