# SPDX-License-Identifier: MIT
"""Readers for embedded image payloads in legacy SketchUp archives."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, BinaryIO

from ..data_structure.images import Texture, normalize_texture_scale

from .parser_types import DibState
from .binary import ArchiveObjectTag, LegacyArchiveReader

if TYPE_CHECKING:
    from .read_context import ObjectReadContext


def read_dib_preview(stream: BinaryIO, *, dib_class_version: int) -> DibState:
    """Read a tagged ``CDib`` image payload."""
    object_tag = LegacyArchiveReader(stream).read_object_tag()
    return read_dib_payload(
        stream,
        object_tag=object_tag,
        dib_class_version=dib_class_version,
    )


def read_dib_payload(
    stream: BinaryIO,
    *,
    object_tag: ArchiveObjectTag,
    dib_class_version: int,
) -> DibState:
    """Read a ``CDib`` body after its archive object tag."""
    reader = LegacyArchiveReader(stream)
    start = reader.tell()
    image_format = None
    image_bytes = b""
    trailing_u32 = None

    if dib_class_version > 0:
        image_format = 4 if dib_class_version == 1 else reader.read_u32()
        byte_count = reader.read_u32()
        image_bytes = reader.read_exact(byte_count, "CDib image bytes")
        if dib_class_version >= 3 and image_format == 1:
            trailing_u32 = reader.read_u32()

    return DibState(
        object_tag=object_tag,
        class_version=dib_class_version,
        payload_start_offset=start,
        image_format=image_format,
        image_bytes=image_bytes,
        trailing_u32=trailing_u32,
        payload_end_offset=reader.tell(),
    )


def looks_like_dib_image(preview: DibState) -> bool:
    """Return whether a decoded DIB has a recognized embedded image signature."""
    if preview.image_format not in {1, 4} or not preview.image_bytes:
        return False
    return preview.image_bytes.startswith((b"\x89PNG", b"PNG", b"BM", b"\xff\xd8"))


def skip_dib_payload(stream: BinaryIO, *, class_version: int | None) -> None:
    """Consume a DIB body when only archive alignment is required."""
    if class_version is None or class_version <= 0:
        return
    reader = LegacyArchiveReader(stream)
    image_format = 4 if class_version == 1 else reader.read_u32()
    byte_count = reader.read_u32()
    reader.read_exact(byte_count, "CDib image bytes")
    if class_version >= 3 and image_format == 1:
        reader.read_u32()


def read_thumbnail_body(
    reader: LegacyArchiveReader,
    *,
    class_version: int,
    read_object: Callable[[], object],
) -> bytes:
    """Resolve a thumbnail camera and return its shared DIB bytes."""
    if class_version not in {0, 1}:
        raise NotImplementedError(f"CThumbnail version {class_version} is not decoded.")
    if class_version == 0:
        from .camera_payloads import read_old_camera_payload

        read_old_camera_payload(reader)
    else:
        read_object()  # Camera metadata is already represented elsewhere.
    dib = read_object()
    return dib.image_bytes if isinstance(dib, DibState) else b""


def read_thumbnail(context: ObjectReadContext, *, class_version: int) -> bytes:
    """Read a thumbnail and resolve its camera and DIB objects."""
    context.read_entity()
    return read_thumbnail_body(
        context.session.reader,
        class_version=class_version,
        read_object=lambda: context.read_object()[1],
    )


def read_texture_body(
    reader: LegacyArchiveReader,
    *,
    class_version: int,
    dib: DibState | None,
) -> Texture:
    """Read a ``CTexture`` body directly into the shared texture object."""
    if class_version not in {4, 6}:
        raise NotImplementedError(f"CTexture version {class_version} is not decoded.")
    texture = Texture()
    texture.x_scale = normalize_texture_scale(reader.read_f64())
    texture.y_scale = normalize_texture_scale(reader.read_f64())
    texture.filename = reader.read_legacy_utf16_string("texture filename")
    reader.read_rgba()
    if dib is not None:
        texture.data = dib.image_bytes
    return texture


def read_texture(context: ObjectReadContext, *, class_version: int) -> Texture:
    """Read a texture and resolve its embedded DIB object."""
    reader = context.session.reader
    dib_object: object | None = None
    if class_version < 5:
        if reader.read_bool():
            dib_object = read_dib_payload(
                context.session.stream,
                object_tag=ArchiveObjectTag("null", 0, 0),
                dib_class_version=context.class_versions.get("CDib", 3),
            )
    else:
        context.read_entity()
        _, dib_object = context.read_object()
    return read_texture_body(
        reader,
        class_version=class_version,
        dib=dib_object if isinstance(dib_object, DibState) else None,
    )


def read_texture_preview(
    stream: BinaryIO,
    *,
    entity_class_version: int,
    texture_class_version: int,
    class_versions: dict[str, int] | None = None,
) -> Texture:
    """Read an unregistered texture from a bounded recovery span."""
    versions = class_versions or {}
    reader = LegacyArchiveReader(stream)
    from .base_payloads import read_entity_header_body

    dib = None
    if texture_class_version < 5:
        if reader.read_bool():
            dib = read_dib_payload(
                stream,
                object_tag=ArchiveObjectTag("null", 0, 0),
                dib_class_version=versions.get("CDib", 3),
            )
    else:
        read_entity_header_body(
            reader,
            class_version=entity_class_version,
            read_reference=reader.read_object_tag,
        )
        dib_tag = reader.read_object_tag()
        if dib_tag.kind == "new_class" and dib_tag.class_name == "CDib":
            dib = read_dib_payload(
                stream,
                object_tag=dib_tag,
                dib_class_version=versions.get("CDib", dib_tag.schema or 0),
            )
    return read_texture_body(reader, class_version=texture_class_version, dib=dib)
