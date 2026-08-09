# SPDX-License-Identifier: MIT
"""Version-aware readers for legacy face texture projection payloads."""

from __future__ import annotations

from ..data_structure.entities import FaceUVProjection, UVPin
from ..data_structure.primitives import Vector2D

from .parser_types import FaceTextureCoordsPayload
from .binary import LegacyArchiveReader
from .read_context import ObjectReadContext


def read_face_texture_coords(context: ObjectReadContext, *, class_version: int) -> FaceTextureCoordsPayload:
    """Read texture coordinates after consuming their entity prefix."""
    context.read_entity()
    return read_face_texture_coords_body(context.session.reader, class_version)


def read_face_texture_coords_body(reader: LegacyArchiveReader, class_version: int) -> FaceTextureCoordsPayload:
    """Read a ``CFaceTextureCoords`` body after its entity header."""
    if class_version > 4:
        raise NotImplementedError("Only SketchUp 8 CFaceTextureCoords versions up to 4 are decoded.")

    attribute_flags = reader.read_u32()
    front_uv = FaceUVProjection()
    front_uv.transform = [reader.read_f64() for _ in range(9)]
    if class_version > 0:
        front_uv.origin = reader.read_vec3_f64()
    back_uv = None
    if class_version > 1:
        back_uv = FaceUVProjection()
        back_uv.transform = [reader.read_f64() for _ in range(9)]
        back_uv.origin = reader.read_vec3_f64()

    if class_version > 2:
        front_uv.pins = _read_texture_push_pins(reader)
        back_pins = _read_texture_push_pins(reader)
        if back_uv is not None:
            back_uv.pins = back_pins

    front_flags = reader.read_u32() if class_version > 3 else None
    back_flags = reader.read_u32() if class_version > 3 else None
    if front_flags is not None and front_flags & 0x02:
        front_uv.projection_direction = front_uv.origin
    if back_uv is not None and back_flags is not None and back_flags & 0x02:
        back_uv.projection_direction = back_uv.origin
    return (
        attribute_flags,
        front_uv,
        back_uv,
        front_flags,
        back_flags,
    )


def _read_texture_push_pins(
    reader: LegacyArchiveReader,
) -> list[UVPin]:
    count = reader.read_u32()
    if count > 1_000_000:
        raise ValueError(f"Unreasonable CFaceTextureCoords pin count: {count}.")
    return [
        UVPin(
            texture_position=Vector2D(reader.read_f64(), reader.read_f64()),
            model_position=Vector2D(reader.read_f64(), reader.read_f64()),
        )
        for _ in range(count)
    ]
