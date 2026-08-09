# SPDX-License-Identifier: MIT
"""Archive adapters for legacy attribute dictionaries and containers."""

from __future__ import annotations

from typing import BinaryIO

from ..data_structure.model_metadata import AttributeDictionary

from .attribute_payloads import read_attribute_container_body, read_named_attribute_body
from .base_payloads import read_entity_header_body
from .binary import ArchiveObjectTag, LegacyArchiveReader
from .parser_types import AttributeContainerPayload
from .read_context import ObjectReadContext


def read_attribute(context: ObjectReadContext, *, class_version: int) -> int:
    """Read the technical payload of a standalone legacy attribute."""
    if class_version != 0:
        raise NotImplementedError("Only SketchUp 8 CAttribute version 0 is decoded.")
    context.read_entity()
    return context.session.reader.read_u32()


def read_named_attribute(context: ObjectReadContext, *, class_version: int) -> AttributeDictionary:
    """Read a named attribute directly into the shared dictionary type."""
    context.read_entity()
    return read_named_attribute_body(context.session.stream, class_version=class_version)


def read_attribute_container(
    context: ObjectReadContext,
    *,
    object_tag: ArchiveObjectTag,
) -> AttributeContainerPayload:
    """Read an attribute container and resolve all named dictionaries."""
    reader = context.session.reader
    start = reader.tell()
    context.read_entity()

    def read_entry() -> tuple[ArchiveObjectTag, object]:
        handle, value = context.read_handle()
        if handle.kind == "null" or handle.object_index is None:
            return handle.tag, value
        # A new-class/new-object tag identifies the runtime class in the byte
        # stream, while the owning entity needs the allocated object index.
        # Normalize it to an object reference for later container lookups.
        return (
            ArchiveObjectTag(
                kind="object_ref",
                raw_tag=handle.tag.raw_tag,
                index=handle.object_index,
                schema=handle.schema,
                class_name=handle.class_name,
            ),
            value,
        )

    return read_attribute_container_body(
        reader,
        object_tag=object_tag,
        payload_start_offset=start,
        read_entry=read_entry,
    )


def read_attribute_container_preview(
    stream: BinaryIO,
    *,
    entity_class_version: int,
    attribute_named_class_version: int,
) -> AttributeContainerPayload:
    """Read the unregistered root model-properties container."""
    reader = LegacyArchiveReader(stream)
    object_tag = reader.read_object_tag()
    start = reader.tell()
    read_entity_header_body(
        reader,
        class_version=entity_class_version,
        read_reference=reader.read_object_tag,
    )

    def read_entry() -> tuple[ArchiveObjectTag, AttributeDictionary | None]:
        tag = reader.read_object_tag()
        if tag.kind == "null":
            return tag, None
        read_entity_header_body(
            reader,
            class_version=entity_class_version,
            read_reference=reader.read_object_tag,
        )
        return tag, read_named_attribute_body(
            stream,
            class_version=attribute_named_class_version,
        )

    return read_attribute_container_body(
        reader,
        object_tag=object_tag,
        payload_start_offset=start,
        read_entry=read_entry,
    )
