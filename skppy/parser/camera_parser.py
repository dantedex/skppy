# SPDX-License-Identifier: MIT
"""Decode modern TLV camera records shared by models and saved scenes.

Camera vectors are required for a record to be usable; incomplete records are
ignored. Optional projection, clipping, image-plane, and 2-D fields retain the
semantic defaults from :class:`~skppy.data_structure.construction.Camera` when
their tags are absent. The model and scene parsers call these functions after
isolating the relevant TLV payload.
"""

from __future__ import annotations

from ..data_structure.construction import Camera
from ..data_structure.primitives import Vector3D
from .tlv import (
    TlvTag,
    index_children,
    iter_records,
    read_bool,
    read_f64_le,
    read_utf8,
    read_vec3,
)


def parse_cameras(camera_block_payload: bytes) -> list[Camera]:
    """Return every complete camera record in a modern camera block."""
    cameras: list[Camera] = []
    for tag, payload in iter_records(camera_block_payload):
        if tag != TlvTag.CAMERA_RECORD:
            continue
        camera = parse_camera_record(payload)
        if camera is not None:
            cameras.append(camera)
    return cameras


def parse_camera_record(payload: bytes) -> Camera | None:
    """Decode one camera payload, rejecting missing required vectors."""
    fields = index_children(payload)
    eye_payload = fields.get(TlvTag.CAMERA_EYE)
    target_payload = fields.get(TlvTag.CAMERA_TARGET)
    up_payload = fields.get(TlvTag.CAMERA_UP)
    if eye_payload is None or len(eye_payload) < 24:
        return None
    if target_payload is None or len(target_payload) < 24:
        return None
    if up_payload is None or len(up_payload) < 24:
        return None

    def optional_float(tag: TlvTag, default: float) -> float:
        value = fields.get(tag)
        return read_f64_le(value) if value is not None and len(value) >= 8 else default

    def nullable_float(tag: TlvTag) -> float | None:
        value = fields.get(tag)
        return read_f64_le(value) if value is not None and len(value) >= 8 else None

    def optional_bool(tag: TlvTag, default: bool) -> bool:
        value = fields.get(tag)
        return read_bool(value) if value is not None else default

    description = fields.get(TlvTag.CAMERA_DESCRIPTION)
    camera = Camera()
    camera.eye = Vector3D(*read_vec3(eye_payload))
    camera.target = Vector3D(*read_vec3(target_payload))
    camera.up = Vector3D(*read_vec3(up_payload))
    camera.fov = optional_float(TlvTag.CAMERA_FOV, 35.0)
    camera.fov_is_height = optional_bool(TlvTag.CAMERA_FOV_IS_HEIGHT, True)
    camera.is_perspective = optional_bool(TlvTag.CAMERA_IS_PERSPECTIVE, True)
    camera.near = optional_float(TlvTag.CAMERA_NEAR, 1.0)
    camera.far = optional_float(TlvTag.CAMERA_FAR, 10000.0)
    camera.name = read_utf8(description) if description is not None else ""
    camera.ortho_height = nullable_float(TlvTag.CAMERA_ORTHO_HEIGHT)
    camera.aspect_ratio = nullable_float(TlvTag.CAMERA_ASPECT)
    camera.legacy_flag = optional_bool(TlvTag.CAMERA_LEGACY_FLAG, False)
    camera.image_width = nullable_float(TlvTag.CAMERA_IMAGE_WIDTH)
    camera.is_2d = optional_bool(TlvTag.CAMERA_IS_2D, False)
    camera.scale_2d = nullable_float(TlvTag.CAMERA_2D_SCALE)
    camera.center_2d_x = nullable_float(TlvTag.CAMERA_2D_CENTER_X)
    camera.center_2d_y = nullable_float(TlvTag.CAMERA_2D_CENTER_Y)
    camera.allow_clipping = optional_bool(TlvTag.CAMERA_ALLOW_CLIPPING, True)
    return camera
