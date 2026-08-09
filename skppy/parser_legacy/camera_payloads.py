# SPDX-License-Identifier: MIT
"""Camera object and root camera-section readers for legacy archives."""

from __future__ import annotations

from typing import BinaryIO

from ..data_structure.construction import Camera
from ..data_structure.primitives import Vector3D

from .parser_types import CameraSectionPayload, DibState
from .binary import ArchiveObjectTag, LegacyArchiveReader
from .image_payloads import looks_like_dib_image, read_dib_payload
from .metadata_payloads import read_camera_payload


def read_camera_section(stream: BinaryIO, *, camera_class_version: int) -> CameraSectionPayload:
    """Read the extra model object tag followed by the root camera object."""
    reader = LegacyArchiveReader(stream)
    leading_tag = reader.read_object_tag()
    leading_dib = _try_read_inline_dib(stream, object_tag=leading_tag)
    camera_tag = reader.read_object_tag()
    camera = read_camera_body(
        stream,
        object_tag=camera_tag,
        camera_class_version=camera_class_version,
    )
    return leading_tag, camera_tag, camera, reader.tell(), leading_dib


def read_root_camera_section(
    stream: BinaryIO,
    *,
    model_class_version: int,
    camera_class_version: int | None,
) -> CameraSectionPayload:
    """Read the root camera using the layout selected by the model schema."""
    null_tag = ArchiveObjectTag("null", 0, 0)
    if model_class_version >= 21:
        if camera_class_version is None:
            raise ValueError("A registered root camera requires a CCamera schema.")
        return read_camera_section(
            stream,
            camera_class_version=camera_class_version,
        )
    if model_class_version >= 11:
        if camera_class_version is None:
            raise ValueError("A registered root camera requires a CCamera schema.")
        camera_tag = LegacyArchiveReader(stream).read_object_tag()
        camera = read_camera_body(
            stream,
            object_tag=camera_tag,
            camera_class_version=camera_class_version,
        )
        return null_tag, camera_tag, camera, stream.tell(), None
    camera = read_old_camera_payload(LegacyArchiveReader(stream))
    return null_tag, null_tag, camera, stream.tell(), None


def read_camera(stream: BinaryIO, *, camera_class_version: int) -> Camera:
    """Read a tagged ``CCamera`` object payload."""
    object_tag = LegacyArchiveReader(stream).read_object_tag()
    return read_camera_body(
        stream,
        object_tag=object_tag,
        camera_class_version=camera_class_version,
    )


def read_camera_body(stream: BinaryIO, *, object_tag: ArchiveObjectTag, camera_class_version: int) -> Camera:
    """Read a ``CCamera`` body whose object tag was already consumed."""
    del object_tag
    return read_camera_payload(LegacyArchiveReader(stream), camera_class_version)


def read_old_camera_payload(reader: LegacyArchiveReader) -> Camera:
    """Read the untagged camera layout used by SketchUp 3 models."""
    camera = Camera()
    camera.eye = Vector3D(*reader.read_vec3_f64())
    direction = Vector3D(*reader.read_vec3_f64())
    camera.up = Vector3D(*reader.read_vec3_f64())
    camera.near = reader.read_f64()
    camera.far = reader.read_f64()
    camera.is_perspective = reader.read_bool()
    camera.fov = reader.read_f64()
    camera.ortho_height = reader.read_f64()
    reader.read_vec3_f64()
    camera.target = camera.eye + direction
    camera.aspect_ratio = 0.0
    return camera


def _try_read_inline_dib(stream: BinaryIO, *, object_tag: ArchiveObjectTag) -> DibState | None:
    if not ((object_tag.kind == "new_class" and object_tag.class_name == "CDib") or object_tag.kind == "class_ref"):
        return None
    payload_start = stream.tell()
    try:
        dib = read_dib_payload(
            stream,
            object_tag=object_tag,
            dib_class_version=object_tag.schema or 3,
        )
    except (EOFError, ValueError):
        stream.seek(payload_start)
        return None
    if looks_like_dib_image(dib):
        return dib
    stream.seek(payload_start)
    return None
