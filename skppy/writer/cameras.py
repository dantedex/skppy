# SPDX-License-Identifier: MIT
"""Modern model and saved-scene camera serialization."""

from __future__ import annotations

import struct
from collections.abc import Iterable
from math import isfinite

from ..data_structure.construction import Camera
from ..data_structure.primitives import Vector3D
from ..parser.tlv import TlvTag
from .tlv import encode_bool, encode_record, encode_records


def encode_camera_record(camera: Camera) -> bytes:
    """Encode one complete ``0x34BC`` camera record."""
    _validate_camera(camera)
    fields = (
        (TlvTag.CAMERA_EYE, _encode_vector(camera.eye)),
        (TlvTag.CAMERA_TARGET, _encode_vector(camera.target)),
        (TlvTag.CAMERA_UP, _encode_vector(camera.up)),
        (TlvTag.CAMERA_NEAR, struct.pack("<d", camera.near)),
        (TlvTag.CAMERA_FAR, struct.pack("<d", camera.far)),
        (TlvTag.CAMERA_IS_PERSPECTIVE, encode_bool(camera.is_perspective)),
        (TlvTag.CAMERA_FOV, struct.pack("<d", camera.fov)),
        (
            TlvTag.CAMERA_ORTHO_HEIGHT,
            struct.pack("<d", _optional(camera.ortho_height, 1.0)),
        ),
        (
            TlvTag.CAMERA_ASPECT,
            struct.pack("<d", _optional(camera.aspect_ratio, 0.0)),
        ),
        (TlvTag.CAMERA_FOV_IS_HEIGHT, encode_bool(camera.fov_is_height)),
        (TlvTag.CAMERA_LEGACY_FLAG, encode_bool(camera.legacy_flag)),
        (TlvTag.CAMERA_DESCRIPTION, camera.name.encode("utf-8")),
        (
            TlvTag.CAMERA_IMAGE_WIDTH,
            struct.pack("<d", _optional(camera.image_width, 0.0)),
        ),
        (TlvTag.CAMERA_IS_2D, encode_bool(camera.is_2d)),
        (
            TlvTag.CAMERA_2D_SCALE,
            struct.pack("<d", _optional(camera.scale_2d, 1.0)),
        ),
        (
            TlvTag.CAMERA_2D_CENTER_X,
            struct.pack("<d", _optional(camera.center_2d_x, 0.0)),
        ),
        (
            TlvTag.CAMERA_2D_CENTER_Y,
            struct.pack("<d", _optional(camera.center_2d_y, 0.0)),
        ),
        (TlvTag.CAMERA_ALLOW_CLIPPING, encode_bool(camera.allow_clipping)),
    )
    return encode_record(TlvTag.CAMERA_RECORD, encode_records(fields))


def encode_cameras(cameras: Iterable[Camera]) -> bytes:
    """Encode the payload of the root current-camera block."""
    values = list(cameras)
    if len(values) != 1:
        raise ValueError("A modern model must contain exactly one current camera")
    return encode_camera_record(values[0])


def _validate_camera(camera: Camera) -> None:
    eye = _components(camera.eye)
    target = _components(camera.target)
    up = _components(camera.up)
    scalars = (
        *eye,
        *target,
        *up,
        camera.near,
        camera.far,
        camera.fov,
        *(
            value
            for value in (
                camera.ortho_height,
                camera.aspect_ratio,
                camera.image_width,
                camera.scale_2d,
                camera.center_2d_x,
                camera.center_2d_y,
            )
            if value is not None
        ),
    )
    if any(not isfinite(value) for value in scalars):
        raise ValueError("Camera values must be finite")
    if eye == target:
        raise ValueError("Camera eye and target must differ")
    if up == (0.0, 0.0, 0.0):
        raise ValueError("Camera up vector must be non-zero")
    _validate_ranges(camera)
    if "\x00" in camera.name:
        raise ValueError("Camera description cannot contain NUL")


def _validate_ranges(camera: Camera) -> None:
    if camera.near <= 0.0 or camera.far <= camera.near:
        raise ValueError("Camera clipping distances must satisfy 0 < near < far")
    if not 0.0 < camera.fov < 180.0:
        raise ValueError("Camera field of view must be in (0, 180)")
    if camera.ortho_height is not None and camera.ortho_height <= 0.0:
        raise ValueError("Camera orthographic height must be positive")
    if camera.aspect_ratio is not None and camera.aspect_ratio < 0.0:
        raise ValueError("Camera aspect ratio must be non-negative")
    if camera.image_width is not None and camera.image_width < 0.0:
        raise ValueError("Camera image width must be non-negative")
    if camera.scale_2d is not None and camera.scale_2d <= 0.0:
        raise ValueError("Camera 2-D scale must be positive")


def _components(value: Vector3D) -> tuple[float, float, float]:
    return float(value.x), float(value.y), float(value.z)


def _encode_vector(value: Vector3D) -> bytes:
    return struct.pack("<3d", *_components(value))


def _optional(value: float | None, default: float) -> float:
    return default if value is None else value
