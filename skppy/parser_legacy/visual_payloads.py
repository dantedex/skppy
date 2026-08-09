# SPDX-License-Identifier: MIT
"""Visual metadata payload bodies for legacy SketchUp archives."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeAlias, TypedDict

from ..data_structure.model_metadata import Watermark, WatermarkManager
from ..data_structure.primitives import Vector3D
from ..data_structure.scene_data import PageBackgroundImage

from .parser_types import DibState
from .binary import ArchiveObjectTag, LegacyArchiveReader
from .read_context import ObjectReadContext

ImageReferencePayload: TypeAlias = tuple[str, int, ArchiveObjectTag, bytes | None, int, int, int, int]


class BackgroundImageFields(TypedDict):
    """Scalar and geometric fields following a background image reference."""

    visible: bool
    opacity: float
    grip_points: tuple[tuple[float, float, float], ...]
    principal_point_delta: tuple[float, float, float]
    radial_distortion_k1: float
    image_source: int


class WatermarkFields(TypedDict):
    """Shared watermark fields preceding its DIB reference."""

    name: str
    position: int
    opacity: float


class ImageReferenceSuffix(TypedDict):
    """Image dimensions and timestamp following an image DIB reference."""

    width: int
    height: int
    file_size: int
    timestamp: int


def read_background_image_fields(reader: LegacyArchiveReader, *, class_version: int) -> BackgroundImageFields:
    """Read ``CBackgroundImage`` fields after its image reference."""
    if class_version != 10:
        raise NotImplementedError("Only SketchUp 8 CBackgroundImage version 10 is decoded.")
    visible = reader.read_bool()
    opacity = reader.read_f64()
    point_count = reader.read_u32()
    grip_points = tuple(reader.read_vec3_f64() for _ in range(point_count))
    return {
        "visible": visible,
        "opacity": opacity,
        "grip_points": grip_points,
        "principal_point_delta": reader.read_vec3_f64(),
        "radial_distortion_k1": reader.read_f64(),
        "image_source": reader.read_u32(),
    }


def read_watermark_fields(reader: LegacyArchiveReader, *, class_version: int) -> WatermarkFields:
    """Read ``CWatermark`` fields preceding its DIB reference."""
    if class_version != 1:
        raise NotImplementedError("Only SketchUp 8 CWatermark version 1 is decoded.")
    reader.read_bool()
    name = reader.read_legacy_utf16_string("CWatermark name")
    reader.read_u32()
    position = reader.read_u32()
    for _ in range(5):
        reader.read_bool()
    reader.read_f64()
    opacity = reader.read_f64()
    reader.read_legacy_utf16_string("CWatermark path")
    return {"name": name, "position": position, "opacity": opacity}


def read_watermark_manager_body(
    reader: LegacyArchiveReader,
    *,
    class_version: int,
    read_object: Callable[[], object],
) -> WatermarkManager:
    """Read a watermark manager body after its entity header."""
    if class_version != 2:
        raise NotImplementedError("Only SketchUp 8 CWatermarkManager version 2 is decoded.")
    manager = WatermarkManager()
    manager.serialized_count = reader.read_u32()
    for _ in range(manager.serialized_count):
        watermark = read_object()
        if isinstance(watermark, Watermark):
            manager.watermarks.append(watermark)
    return manager


def read_image_reference_prefix(reader: LegacyArchiveReader, *, class_version: int) -> tuple[str, int]:
    """Read an ``ImageReference`` path and state before its DIB reference."""
    if class_version != 3:
        raise NotImplementedError("Only SketchUp 8 ImageReference version 3 is decoded.")
    return (
        reader.read_legacy_utf16_string("image reference path"),
        reader.read_u32(),
    )


def read_image_reference_suffix(reader: LegacyArchiveReader) -> ImageReferenceSuffix:
    """Read ``ImageReference`` fields following its DIB reference."""
    return {
        "width": reader.read_u32(),
        "height": reader.read_u32(),
        "file_size": reader.read_u32(),
        "timestamp": reader.read_u32(),
    }


def read_image_reference(
    reader: LegacyArchiveReader,
    *,
    class_version: int,
    read_object: Callable[[], tuple[ArchiveObjectTag, object]],
) -> ImageReferencePayload:
    """Read an image reference and resolve its intervening DIB object."""
    path, state = read_image_reference_prefix(reader, class_version=class_version)
    dib_tag, value = read_object()
    suffix = read_image_reference_suffix(reader)
    return (
        path,
        state,
        dib_tag,
        value.image_bytes if isinstance(value, DibState) else None,
        suffix["width"],
        suffix["height"],
        suffix["file_size"],
        suffix["timestamp"],
    )


def read_background_image_body(
    reader: LegacyArchiveReader,
    *,
    class_version: int,
    image_reference: ImageReferencePayload,
) -> PageBackgroundImage:
    """Read background-image fields into the shared page representation."""
    path, reference_state, _, image_data, width, height, file_size, timestamp = image_reference
    fields = read_background_image_fields(reader, class_version=class_version)
    return PageBackgroundImage(
        path=path,
        reference_state=reference_state,
        image_data=image_data,
        width=width,
        height=height,
        file_size=file_size,
        timestamp=timestamp,
        visible=fields["visible"],
        opacity=fields["opacity"],
        grip_points=[Vector3D(*point) for point in fields["grip_points"]],
        principal_point_delta=Vector3D(*fields["principal_point_delta"]),
        radial_distortion_k1=fields["radial_distortion_k1"],
        image_source=fields["image_source"],
    )


def read_background_image(
    context: ObjectReadContext,
    *,
    class_version: int,
) -> PageBackgroundImage:
    """Read a background image and resolve its embedded DIB reference."""
    reader = context.session.reader
    context.read_entity()
    image_reference = read_image_reference(
        reader,
        class_version=3,
        read_object=context.read_object,
    )
    return read_background_image_body(
        reader,
        class_version=class_version,
        image_reference=image_reference,
    )
