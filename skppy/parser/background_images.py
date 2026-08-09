# SPDX-License-Identifier: MIT
"""Parser for modern match-photo/page-background images."""

from __future__ import annotations

import struct
import zipfile

from ..data_structure.primitives import Vector3D
from ..data_structure.scene_data import PageBackgroundImage
from .tlv import (
    TlvTag,
    find_child,
    iter_records,
    read_bool,
    read_f64_le,
    read_id_from_wrapper,
    read_utf8,
)


def parse_background_images(payload: bytes, archive: zipfile.ZipFile) -> dict[int, PageBackgroundImage]:
    """Decode a root ``0x0201`` image collection by persistent ID."""
    images: dict[int, PageBackgroundImage] = {}
    for tag, record in iter_records(payload):
        if tag != TlvTag.BACKGROUND_IMAGE_RECORD:
            continue
        identity = find_child(record, TlvTag.ID_WRAPPER)
        image_id = read_id_from_wrapper(identity) if identity else 0
        if image_id:
            images[image_id] = _parse_background_image(record, image_id, archive)
    return images


def _parse_background_image(payload: bytes, image_id: int, archive: zipfile.ZipFile) -> PageBackgroundImage:
    reference_wrapper = find_child(payload, TlvTag.BACKGROUND_IMAGE_REFERENCE)
    reference = find_child(reference_wrapper, TlvTag.IMAGE_REFERENCE_RECORD) if reference_wrapper else None
    path = _child(reference, TlvTag.IMAGE_REFERENCE_PATH)
    dib_wrapper = _child(reference, TlvTag.IMAGE_REFERENCE_DIB)
    dib = find_child(dib_wrapper, TlvTag.DIB_RECORD) if dib_wrapper else None
    image_data = _image_data(dib, archive)
    grip_payload = find_child(payload, TlvTag.BACKGROUND_IMAGE_GRIP_POINTS)
    delta_payload = find_child(payload, TlvTag.BACKGROUND_IMAGE_PRINCIPAL_DELTA)
    return PageBackgroundImage(
        path=read_utf8(path) if path is not None else "",
        reference_state=_i32(_child(reference, TlvTag.IMAGE_REFERENCE_STATE)),
        image_data=image_data,
        width=_i32(_child(reference, TlvTag.IMAGE_REFERENCE_WIDTH)),
        height=_i32(_child(reference, TlvTag.IMAGE_REFERENCE_HEIGHT)),
        file_size=_i32(_child(reference, TlvTag.IMAGE_REFERENCE_FILE_SIZE)),
        timestamp=_i32(_child(reference, TlvTag.IMAGE_REFERENCE_TIMESTAMP)),
        visible=_bool(find_child(payload, TlvTag.BACKGROUND_IMAGE_VISIBLE)),
        opacity=_f64(find_child(payload, TlvTag.BACKGROUND_IMAGE_OPACITY), 1.0),
        grip_points=_points(grip_payload),
        principal_point_delta=_vector(delta_payload),
        radial_distortion_k1=_f64(find_child(payload, TlvTag.BACKGROUND_IMAGE_RADIAL_DISTORTION), 0.0),
        image_source=_i32(find_child(payload, TlvTag.BACKGROUND_IMAGE_SOURCE)),
        id=image_id,
    )


def _child(payload: bytes | None, tag: int) -> bytes | None:
    return find_child(payload, tag) if payload is not None else None


def _i32(payload: bytes | None) -> int:
    return struct.unpack_from("<i", payload)[0] if payload and len(payload) >= 4 else 0


def _f64(payload: bytes | None, default: float) -> float:
    return read_f64_le(payload) if payload and len(payload) >= 8 else default


def _bool(payload: bytes | None) -> bool:
    return read_bool(payload) if payload else False


def _points(payload: bytes | None) -> list[Vector3D]:
    if not payload:
        return []
    return [Vector3D(*struct.unpack_from("<ddd", payload, offset)) for offset in range(0, len(payload) - 23, 24)]


def _vector(payload: bytes | None) -> Vector3D:
    if payload and len(payload) >= 24:
        return Vector3D(*struct.unpack_from("<ddd", payload))
    return Vector3D(0.0, 0.0, 0.0)


def _image_data(dib: bytes | None, archive: zipfile.ZipFile) -> bytes | None:
    if dib is None:
        return None
    binary = find_child(dib, TlvTag.DIB_BINARY)
    if binary is not None:
        return binary
    external = find_child(dib, TlvTag.DIB_EXTERNAL_PATH)
    if external:
        try:
            return archive.read(read_utf8(external))
        except KeyError:
            pass
    return None
