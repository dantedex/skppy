# SPDX-License-Identifier: MIT
"""
Image texture data class.

.. module:: skppy.data_structure.images
   :synopsis: Texture data structure

Textures are image files referenced by materials. The raw image data
can be extracted from the ZIP archive.

Example
-------
::

    tex = Texture(filename="brick_wall.png", x_scale=100.0, y_scale=100.0)
    if tex.data:
        with open(tex.filename, "wb") as f:
            f.write(tex.data)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


def normalize_texture_scale(value: float, default: float = 1.0) -> float:
    """Return a finite, non-zero texture scale suitable for UV division.

    Negative scales are retained because they can intentionally mirror a
    texture. Zero, near-zero, NaN, and infinite values cannot define a physical
    tile size and fall back to one SketchUp inch.
    """
    scale = float(value)
    return scale if math.isfinite(scale) and abs(scale) >= 1e-12 else default


@dataclass(slots=True)
class Texture:
    """
    An image texture referenced by a Material.

    Parameters
    ----------
    filename : str
        Original filename as stored in the .skp (e.g., ``"brick.jpg"``).
    x_scale : float, optional
        Width of one texture tile in inches. Default 1.0.
    y_scale : float, optional
        Height of one texture tile in inches. Default 1.0.
    data : bytes or None, optional
        Raw image bytes (JPEG, PNG, etc.). ``None`` if not extracted.
    brightness : float, optional
        Source renderer's texture multiplier. Default 1.0.
    inverted : bool, optional
        Whether the source renderer inverts the texture values.

    Examples
    --------
    >>> tex = Texture(filename="brick.jpg", x_scale=100.0, y_scale=50.0)
    >>> tex.filename
    'brick.jpg'
    >>> tex.x_scale
    100.0
    """

    filename: str = ""
    x_scale: float = 1.0
    y_scale: float = 1.0
    data: Optional[bytes] = None
    brightness: float = 1.0
    inverted: bool = False

    def __post_init__(self) -> None:
        """Keep newly constructed textures safe for immediate UV evaluation."""
        self.x_scale = normalize_texture_scale(self.x_scale)
        self.y_scale = normalize_texture_scale(self.y_scale)
