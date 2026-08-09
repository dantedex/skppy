# SPDX-License-Identifier: MIT
"""Versioned material payload decoding for legacy archives."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, BinaryIO

from ..data_structure.materials import Color, Material
from ..data_structure.images import Texture

from .parser_types import MaterialState, EntityHeaderState
from .binary import LegacyArchiveReader
from .base_payloads import read_entity_header_body
from .image_payloads import read_texture, read_texture_preview

if TYPE_CHECKING:
    from .read_context import ObjectReadContext


def read_material(context: ObjectReadContext, *, class_version: int) -> MaterialState:
    """Read a material and its optional embedded shared texture."""
    reader = context.session.reader
    start = reader.tell()
    entity_header = context.read_entity()
    return read_material_payload(
        reader,
        class_version=class_version,
        payload_start_offset=start,
        entity_header=entity_header,
        read_texture=lambda: read_texture(
            context,
            class_version=context.class_versions.get("CTexture", 6),
        ),
    )


def read_material_manager(context: ObjectReadContext, *, class_version: int) -> tuple[MaterialState, ...]:
    """Read a material manager as a collection of resolved materials."""
    context.read_entity()
    return read_material_manager_body(
        context.session.reader,
        class_version=class_version,
        read_object=lambda: context.read_object()[1],
    )


def read_material_preview(
    stream: BinaryIO,
    *,
    entity_class_version: int,
    material_class_version: int,
    class_versions: dict[str, int] | None = None,
) -> MaterialState:
    """Read an unregistered material from a bounded recovery span."""
    versions = class_versions or {}
    reader = LegacyArchiveReader(stream)
    start = reader.tell()
    entity_header = read_entity_header_body(
        reader,
        class_version=entity_class_version,
        read_reference=reader.read_object_tag,
    )
    return read_material_payload(
        reader,
        class_version=material_class_version,
        payload_start_offset=start,
        entity_header=entity_header,
        read_texture=lambda: read_texture_preview(
            stream,
            entity_class_version=entity_class_version,
            texture_class_version=versions.get("CTexture", 6),
            class_versions=versions,
        ),
    )


def read_material_payload(
    reader: LegacyArchiveReader,
    *,
    class_version: int,
    payload_start_offset: int,
    entity_header: EntityHeaderState,
    read_texture: Callable[[], Texture],
) -> MaterialState:
    """Consume a ``CMaterial`` body and construct its shared material."""
    if class_version != 12:
        raise NotImplementedError("Only SketchUp 8 CMaterial version 12 is decoded.")

    material = Material()
    material.name = reader.read_legacy_utf16_string("material name")
    material.texture = read_texture() if reader.read_bool() else None
    material.has_texture = material.texture is not None
    used_by_layer = reader.read_bool()
    color = reader.read_rgba()
    material.color = Color(*color)
    string_90 = reader.read_legacy_utf16_string("material string")
    material_type = reader.read_u32()
    colorize_type = reader.read_u32()
    transparency = reader.read_f64()
    use_transparency = reader.read_bool()
    if use_transparency:
        material.alpha = min(max(1.0 - transparency, 0.0), 1.0)

    # MaterialState binds the mutable public material to fixed archive offsets
    # and flags, so its technical wrapper is constructed atomically at the end.
    return MaterialState(
        class_version=class_version,
        payload_start_offset=payload_start_offset,
        entity_header=entity_header,
        material=material,
        used_by_layer=used_by_layer,
        color=color,
        string_90=string_90,
        material_type=material_type,
        colorize_type=colorize_type,
        transparency=transparency,
        use_transparency=use_transparency,
        payload_end_offset=reader.tell(),
    )


def read_material_manager_body(
    reader: LegacyArchiveReader,
    *,
    class_version: int,
    read_object: Callable[[], object],
) -> tuple[MaterialState, ...]:
    """Read a material manager body after its entity header."""
    if class_version != 4:
        raise NotImplementedError("Only SketchUp 8 CMaterialManager version 4 is decoded.")
    material_count = reader.read_u32()
    materials = tuple(material for _ in range(material_count) if isinstance((material := read_object()), MaterialState))
    if class_version >= 2:
        read_object()  # Current material is runtime selection state only.
    return materials
