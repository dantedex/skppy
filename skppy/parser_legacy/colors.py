# SPDX-License-Identifier: MIT
"""Color conversion helpers for legacy CArchive payloads."""

from __future__ import annotations


def rgba_bytes_to_argb(color: tuple[int, int, int, int]) -> int:
    """Pack serialized RGBA bytes into the public ``0xAARRGGBB`` form."""
    red, green, blue, alpha = color
    return (alpha << 24) | (red << 16) | (green << 8) | blue
