# SPDX-License-Identifier: MIT
"""Modern match-photo/page-background image serialization."""

from __future__ import annotations

import struct
from hashlib import sha256
from collections.abc import Iterable, Mapping
from pathlib import PurePath

from ..data_structure.scene_data import PageBackgroundImage
from ..parser.tlv import TlvTag
from .tlv import encode_compact_int, encode_record, encode_records


def encode_background_images(
    images: Iterable[PageBackgroundImage],
    id_map: Mapping[int, int],
) -> bytes:
    """Encode the root background-image collection payload."""
    return b"".join(
        encode_record(
            TlvTag.BACKGROUND_IMAGE_RECORD,
            _encode_background_image(image, id_map[id(image)]),
        )
        for image in images
    )


def background_image_entries(
    images: Iterable[PageBackgroundImage],
) -> dict[str, bytes]:
    """Return canonical ``matched_photos/*`` resources."""
    entries: dict[str, bytes] = {}
    for image in images:
        if image.image_data is None:
            raise ValueError("Background images require image data")
        path = _external_path(image)
        if path in entries:
            raise ValueError(f"Duplicate background-image resource path: {path}")
        entries[path] = image.image_data
    return entries


def _encode_background_image(image: PageBackgroundImage, image_id: int) -> bytes:
    _validate_image(image)
    image_reference = encode_record(
        TlvTag.IMAGE_REFERENCE_RECORD,
        encode_records(
            (
                (TlvTag.IMAGE_REFERENCE_PATH, image.path.encode("utf-8")),
                (
                    TlvTag.IMAGE_REFERENCE_STATE,
                    struct.pack("<i", image.reference_state),
                ),
                (
                    TlvTag.IMAGE_REFERENCE_DIB,
                    _encode_dib(image.image_data or b"", _external_path(image)),
                ),
                (TlvTag.IMAGE_REFERENCE_WIDTH, struct.pack("<i", image.width)),
                (TlvTag.IMAGE_REFERENCE_HEIGHT, struct.pack("<i", image.height)),
                (TlvTag.IMAGE_REFERENCE_FILE_SIZE, struct.pack("<i", image.file_size)),
                (TlvTag.IMAGE_REFERENCE_TIMESTAMP, struct.pack("<i", image.timestamp)),
            )
        ),
    )
    grip_points = b"".join(struct.pack("<ddd", point.x, point.y, point.z) for point in image.grip_points)
    delta = image.principal_point_delta
    return encode_records(
        (
            (
                TlvTag.ID_WRAPPER,
                encode_record(TlvTag.ID_VALUE, encode_compact_int(image_id)),
            ),
            (TlvTag.BACKGROUND_IMAGE_REFERENCE, image_reference),
            (TlvTag.BACKGROUND_IMAGE_VISIBLE, bytes((image.visible,))),
            (TlvTag.BACKGROUND_IMAGE_OPACITY, struct.pack("<d", image.opacity)),
            (TlvTag.BACKGROUND_IMAGE_GRIP_POINTS, grip_points),
            (
                TlvTag.BACKGROUND_IMAGE_PRINCIPAL_DELTA,
                struct.pack("<ddd", delta.x, delta.y, delta.z),
            ),
            (
                TlvTag.BACKGROUND_IMAGE_RADIAL_DISTORTION,
                struct.pack("<d", image.radial_distortion_k1),
            ),
            (TlvTag.BACKGROUND_IMAGE_SOURCE, struct.pack("<i", image.image_source)),
        )
    )


def _encode_dib(image_data: bytes, external_path: str) -> bytes:
    file_type = 4 if _image_extension(image_data) == "png" else 1
    fields = [
        (TlvTag.DIB_FILE_TYPE, struct.pack("<i", file_type)),
        (TlvTag.DIB_EXTERNAL_PATH, external_path.encode("utf-8")),
    ]
    if file_type == 1:
        fields.append((TlvTag.DIB_JPEG_QUALITY, struct.pack("<i", 90)))
    return encode_record(TlvTag.DIB_RECORD, encode_records(fields))


def _external_path(image: PageBackgroundImage) -> str:
    extension = _image_extension(image.image_data or b"")
    source_name = PurePath(image.path.replace("\\", "/")).name
    stem = (
        source_name.rsplit(".", 1)[0]
        if source_name
        else f"background-{sha256(image.image_data or b'').hexdigest()[:12]}"
    )
    if not stem or any(character in stem for character in "/\\"):
        raise ValueError("Background image paths must have a path-safe file name")
    return f"matched_photos/{stem}.{extension}"


def _image_extension(image_data: bytes) -> str:
    if image_data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if image_data.startswith(b"\xff\xd8"):
        return "jpg"
    raise ValueError("Background image data must be PNG or JPEG")


def _validate_image(image: PageBackgroundImage) -> None:
    if image.image_data is None:
        raise ValueError("Background images require image data")
    _image_extension(image.image_data)
    if not 0.0 <= image.opacity <= 1.0:
        raise ValueError("Background image opacity must be between 0 and 1")
    for field_name in (
        "reference_state",
        "width",
        "height",
        "file_size",
        "timestamp",
        "image_source",
    ):
        value = getattr(image, field_name)
        if not -(2**31) <= value < 2**31:
            raise ValueError(f"Background image {field_name} must fit in i32")
