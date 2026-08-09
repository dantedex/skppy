# SPDX-License-Identifier: MIT
"""Shared component entity payloads for legacy SketchUp archives."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import BinaryIO

from ..data_structure.entities import ComponentInstance, Group, Image

from .binary import ArchiveObjectHandle, LegacyArchiveReader
from .parser_types import DefinitionListPayload, RootComponentPayload
from .session import LegacyArchiveSession


def read_root_component(stream: BinaryIO) -> RootComponentPayload:
    """Read the root component prelude that introduces serialized entities."""
    reader = LegacyArchiveReader(stream)
    start = reader.tell()
    first_value = reader.read_u32()
    entity_count = first_value
    leading_value = None
    if first_value == 0:
        second_start = reader.tell()
        second_value = reader.read_u32()
        if second_value < 1_000_000:
            entity_count = second_value
            leading_value = first_value
        else:
            stream.seek(second_start)
    return start, entity_count, reader.tell(), leading_value


def read_definition_list_payload(
    session: LegacyArchiveSession,
    *,
    class_version: int,
    resolve: Callable[[ArchiveObjectHandle], object],
) -> DefinitionListPayload:
    """Read definition references while delegating archive-object resolution."""
    if class_version != 0:
        raise NotImplementedError("Only SketchUp 8 CDefinitionList version 0 is decoded.")
    start = session.tell()
    count = session.reader.read_u32()
    tags = []
    for _ in range(count):
        handle = session.read_object_handle()
        tags.append(handle.tag)
        # Definitions can be declared inline at their first list entry. Resolve
        # them now so the next iteration starts at the following object tag.
        if handle.kind == "new_object":
            resolve(handle)
    return tuple(tags), start, session.tell()


def read_component_instance_body(
    reader: LegacyArchiveReader,
    *,
    class_version: int,
    definition_id: int,
    material_id: int | None,
) -> ComponentInstance:
    """Read a ``CComponentInstance`` body after its archive references."""
    if class_version not in {3, 4, 5, 6}:
        raise NotImplementedError("Only CComponentInstance versions 3 through 6 are decoded.")
    # Populate in wire order. definition_id/material_id are still archive table
    # indices and are translated by entity_builder after definitions exist.
    instance = ComponentInstance(definition_id=definition_id, material_id=material_id)
    instance.transform = [reader.read_f64() for _ in range(13)]
    if class_version > 3:
        instance.name = reader.read_legacy_utf16_string("component instance name") or None
    instance.guid = reader.read_exact(16, "component instance GUID") if class_version >= 5 else uuid.uuid4().bytes
    return instance


def component_instance_as_group(component_instance: ComponentInstance, *, class_version: int) -> Group:
    """Convert a confirmed ``CGroup`` component base to the shared group type."""
    if class_version != 1:
        raise NotImplementedError("Only SketchUp 8 CGroup version 1 is decoded.")
    return Group(
        id=component_instance.id,
        guid=component_instance.guid,
        name=component_instance.name,
        definition_id=component_instance.definition_id,
        transform=component_instance.transform,
        material_id=component_instance.material_id,
        layer_id=component_instance.layer_id,
    )


def component_instance_as_image(component_instance: ComponentInstance, *, class_version: int) -> Image:
    """Convert a confirmed ``CImage`` component base to the shared image type."""
    if class_version != 1:
        raise NotImplementedError("Only SketchUp 8 CImage version 1 is decoded.")
    return Image(
        id=component_instance.id,
        guid=component_instance.guid,
        name=component_instance.name,
        definition_id=component_instance.definition_id,
        transform=component_instance.transform,
        material_id=component_instance.material_id,
        layer_id=component_instance.layer_id,
    )
