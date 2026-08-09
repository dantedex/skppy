# SPDX-License-Identifier: MIT
"""Modern watermark-manager TLV serialization."""

from __future__ import annotations

import struct
from collections.abc import Mapping

from ..data_structure.model_metadata import Watermark, WatermarkManager
from ..parser.tlv import TlvTag
from .tlv import encode_compact_int, encode_record, encode_records


def encode_watermark_manager(
    manager: WatermarkManager,
    watermark_id_map: Mapping[int, int] | None = None,
) -> bytes:
    """Encode the payload of the root watermark-manager block."""
    if manager.serialized_count not in (0, len(manager.watermarks)):
        raise ValueError("Serialized watermark count must match the watermark list")
    records = b"".join(
        encode_record(
            TlvTag.WATERMARK_RECORD,
            _encode_watermark(
                mark,
                (watermark_id_map[mark.id or index] if watermark_id_map is not None else mark.id or index),
            ),
        )
        for index, mark in enumerate(manager.watermarks, start=1)
    )
    return encode_record(
        TlvTag.WATERMARK_MANAGER_RECORD,
        encode_records(
            (
                (TlvTag.WATERMARK_LIST, records),
                (
                    TlvTag.WATERMARK_SERIALIZED_COUNT,
                    struct.pack("<I", len(manager.watermarks)),
                ),
            )
        ),
    )


def _encode_watermark(mark: Watermark, watermark_id: int) -> bytes:
    if not mark.name:
        raise ValueError("Watermark names must be non-empty")
    if any(character in mark.name for character in "/\\"):
        raise ValueError("Watermark names must be path-safe")
    if mark.image_data is None:
        raise ValueError("Watermarks require image data")
    if not 0.0 <= mark.opacity <= 1.0:
        raise ValueError("Watermark opacity must be between 0 and 1")
    if not 0 <= mark.position <= 5:
        raise ValueError("Watermark position must be between 0 and 5")

    tiled = mark.position == 5
    fitting_type = 0 if tiled else 2
    screen_position = 4 if tiled else mark.position
    extension = _image_extension(mark.image_data)
    image_path = f"watermarks/{mark.name}.{extension}"
    return encode_records(
        (
            (
                TlvTag.ID_WRAPPER,
                encode_record(TlvTag.ID_VALUE, encode_compact_int(watermark_id)),
            ),
            (TlvTag.WATERMARK_NAME, b""),
            (TlvTag.WATERMARK_FILE_INFO_FOUND, b"\x00"),
            (TlvTag.WATERMARK_FILE_TIME, struct.pack("<i", 0)),
            (TlvTag.WATERMARK_FILE_NAME, mark.name.encode("utf-8")),
            (TlvTag.WATERMARK_POSITION, struct.pack("<i", screen_position)),
            (TlvTag.WATERMARK_IMAGE, _encode_dib(mark.image_data, image_path)),
            (TlvTag.WATERMARK_TILED, bytes((tiled,))),
            (TlvTag.WATERMARK_STRETCHED, b"\x00"),
            (TlvTag.WATERMARK_MAINTAIN_ASPECT, bytes((not tiled,))),
            (TlvTag.WATERMARK_FITTING_TYPE, struct.pack("<i", fitting_type)),
            (TlvTag.WATERMARK_STRETCH_TYPE, struct.pack("<i", 0 if tiled else 1)),
            (TlvTag.WATERMARK_BACKGROUND, b"\x00"),
            (TlvTag.WATERMARK_SCALE, struct.pack("<d", 0.5)),
            (TlvTag.WATERMARK_INTENSITY_ALPHA, b"\x01"),
            (TlvTag.WATERMARK_OPACITY, struct.pack("<d", mark.opacity)),
        )
    )


def watermark_entries(manager: WatermarkManager | None) -> dict[str, bytes]:
    """Return canonical external image resources for a watermark manager."""
    if manager is None:
        return {}
    entries: dict[str, bytes] = {}
    for mark in manager.watermarks:
        if mark.image_data is None:
            raise ValueError("Watermarks require image data")
        extension = _image_extension(mark.image_data)
        path = f"watermarks/{mark.name}.{extension}"
        if path in entries:
            raise ValueError(f"Duplicate watermark resource path: {path}")
        entries[path] = mark.image_data
    return entries


def _encode_dib(image_data: bytes, external_path: str) -> bytes:
    file_type = 4 if _image_extension(image_data) == "png" else 1
    fields = [
        (TlvTag.DIB_FILE_TYPE, struct.pack("<i", file_type)),
        (TlvTag.DIB_EXTERNAL_PATH, external_path.encode("utf-8")),
    ]
    if file_type == 1:
        fields.append((TlvTag.DIB_JPEG_QUALITY, struct.pack("<i", 90)))
    return encode_record(TlvTag.DIB_RECORD, encode_records(fields))


def _image_extension(image_data: bytes) -> str:
    if image_data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if image_data.startswith(b"\xff\xd8"):
        return "jpg"
    raise ValueError("Watermark image data must be PNG or JPEG")
