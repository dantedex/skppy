# SPDX-License-Identifier: MIT
"""Shared layer payload decoding for legacy SketchUp archives."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, BinaryIO

from ..data_structure.layers import Layer, LayerFolder

from .parser_types import (
    LayerState,
    MaterialState,
    EntityHeaderState,
    LayerManagerPayload,
)
from .binary import ArchiveObjectTag, LegacyArchiveReader
from .base_payloads import read_entity_header_body
from .material_payloads import read_material, read_material_preview

if TYPE_CHECKING:
    from .read_context import ObjectReadContext


def read_layer(
    context: ObjectReadContext,
    *,
    object_tag: ArchiveObjectTag,
    class_version: int,
) -> LayerState:
    """Read a layer and its embedded material into shared data objects."""
    reader = context.session.reader
    start = reader.tell()
    entity_header = context.read_entity()
    layer = Layer()
    read_layer_identity(reader, layer)
    material = read_material(
        context,
        class_version=context.class_versions.get("CMaterial", 12),
    )
    return finish_layer_payload(
        reader,
        class_version=class_version,
        object_tag=object_tag,
        payload_start_offset=start,
        entity_header=entity_header,
        layer=layer,
        material=material,
        read_reference=context.read_reference,
    )


def read_layer_manager(context: ObjectReadContext, *, class_version: int) -> LayerManagerPayload:
    """Read a layer manager and resolve its layer collection."""
    reader = context.session.reader
    start = reader.tell()
    context.read_entity()

    def read_resolved_layer() -> LayerState | None:
        _, value = context.read_object()
        return value if isinstance(value, LayerState) else None

    def read_resolved_group() -> LayerFolder:
        if class_version >= 7:
            return read_layer_group(context)
        _, value = context.read_object()
        if not isinstance(value, LayerFolder):
            raise ValueError("Expected a CLayerGroup object.")
        return value

    return read_layer_manager_body(
        reader,
        class_version=class_version,
        payload_start_offset=start,
        read_layer=read_resolved_layer,
        read_reference=context.read_reference,
        read_layer_group=read_resolved_group,
    )


def read_layer_preview(
    stream: BinaryIO,
    *,
    entity_class_version: int,
    layer_class_version: int,
    material_class_version: int,
    class_versions: dict[str, int] | None = None,
) -> LayerState:
    """Read an unregistered layer and material from a root archive section."""
    reader = LegacyArchiveReader(stream)
    object_tag = reader.read_object_tag()
    start = reader.tell()
    entity_header = read_entity_header_body(
        reader,
        class_version=entity_class_version,
        read_reference=reader.read_object_tag,
    )
    layer = Layer()
    read_layer_identity(reader, layer)
    material = read_material_preview(
        stream,
        entity_class_version=entity_class_version,
        material_class_version=material_class_version,
        class_versions=class_versions,
    )
    return finish_layer_payload(
        reader,
        class_version=layer_class_version,
        object_tag=object_tag,
        payload_start_offset=start,
        entity_header=entity_header,
        layer=layer,
        material=material,
        read_reference=reader.read_object_tag,
    )


def read_layer_manager_preview(
    stream: BinaryIO,
    *,
    entity_class_version: int,
    layer_manager_class_version: int,
    layer_class_version: int,
    material_class_version: int,
    class_versions: dict[str, int] | None = None,
) -> LayerManagerPayload:
    """Read the untagged root layer manager and its inline layers."""
    reader = LegacyArchiveReader(stream)
    start = reader.tell()
    read_entity_header_body(
        reader,
        class_version=entity_class_version,
        read_reference=reader.read_object_tag,
    )
    return read_layer_manager_body(
        reader,
        class_version=layer_manager_class_version,
        payload_start_offset=start,
        read_layer=lambda: read_layer_preview(
            stream,
            entity_class_version=entity_class_version,
            layer_class_version=layer_class_version,
            material_class_version=material_class_version,
            class_versions=class_versions,
        ),
        read_reference=reader.read_object_tag,
    )


def read_layer_identity(reader: LegacyArchiveReader, layer: Layer) -> None:
    """Populate layer identity fields preceding its material payload."""
    layer.name = reader.read_legacy_utf16_string("layer name")
    layer.visible = not reader.read_bool()


def finish_layer_payload(
    reader: LegacyArchiveReader,
    *,
    class_version: int,
    object_tag: ArchiveObjectTag,
    payload_start_offset: int,
    entity_header: EntityHeaderState,
    layer: Layer,
    material: MaterialState,
    read_reference: Callable[[], ArchiveObjectTag],
) -> LayerState:
    """Read the layer tail and construct its shared layer object."""
    if class_version > 1:
        layer.page_behavior = reader.read_u32()
    if class_version > 2:
        read_reference()
    # LayerState freezes the archive identity around an already populated public
    # Layer; no incomplete reference state should reach model assembly.
    return LayerState(
        object_tag=object_tag,
        payload_start_offset=payload_start_offset,
        entity_header=entity_header,
        layer=layer,
        material=material,
        payload_end_offset=reader.tell(),
    )


def read_layer_manager_body(
    reader: LegacyArchiveReader,
    *,
    class_version: int,
    payload_start_offset: int,
    read_layer: Callable[[], LayerState | None],
    read_reference: Callable[[], ArchiveObjectTag],
    read_layer_group: Callable[[], LayerFolder] | None = None,
) -> LayerManagerPayload:
    """Read a layer manager body after its entity header."""
    layer_count = reader.read_u32()
    layers = tuple(layer for _ in range(layer_count) if (layer := read_layer()) is not None)
    active_layer = read_reference() if class_version == 3 or layer_count > 0 else None
    folders: tuple[LayerFolder, ...] = ()
    if class_version == 6:
        folder_count = reader.read_u32()
        folders = tuple(
            folder
            for _ in range(folder_count)
            if read_layer_group is not None and isinstance((folder := read_layer_group()), LayerFolder)
        )
    elif class_version >= 7:
        if read_layer_group is None:
            raise ValueError("CLayerManager v7 requires a root CLayerGroup reader.")
        folders = tuple(read_layer_group().child_folders)
    return layers, active_layer, folders, payload_start_offset, reader.tell()


def read_layer_group(
    context: ObjectReadContext,
    *,
    class_version: int | None = None,
) -> LayerFolder:
    """Read a layer-group tree into shared ``LayerFolder`` objects."""
    version = class_version or context.class_versions.get("CLayerGroup", 3)
    if version not in {1, 2, 3}:
        raise NotImplementedError(f"Unsupported CLayerGroup schema {version}.")
    context.read_entity()
    reader = context.session.reader
    folder = LayerFolder()
    folder.name = reader.read_legacy_utf16_string("CLayerGroup name")
    for _ in range(reader.read_u32()):
        _, value = context.read_object()
        if isinstance(value, LayerFolder):
            folder.child_folders.append(value)
    for _ in range(reader.read_u32()):
        handle, _ = context.read_handle()
        if handle.object_index is not None:
            folder.child_layer_ids.append(handle.object_index)
    if version > 1:
        folder.visible = reader.read_bool()
    if version > 2:
        reader.read_bool()  # Expanded state has no shared LayerFolder field.
    return folder
