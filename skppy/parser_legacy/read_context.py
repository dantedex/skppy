# SPDX-License-Identifier: MIT
"""Shared recursive-read context for legacy archive payload adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from .parser_types import (
    DrawingElementState,
    EntityHeaderState,
    SupportedObjectPayload,
)
from .base_payloads import read_entity_header_body
from .binary import ArchiveObjectHandle, ArchiveObjectTag
from .geometry_payloads import read_drawing_element_body
from .session import LegacyArchiveSession

ObjectResolver = Callable[[ArchiveObjectHandle], SupportedObjectPayload]


@dataclass(slots=True)
class ObjectReadContext:
    """Provide domain readers with version and recursive-reference handling."""

    session: LegacyArchiveSession
    class_versions: dict[str, int]
    resolve: ObjectResolver
    current_object_index: int | None = None

    def read_handle(self) -> tuple[ArchiveObjectHandle, SupportedObjectPayload]:
        """Read one archive handle together with its resolved value."""
        handle = self.session.read_object_handle()
        return handle, self.resolve(handle)

    def read_object(self) -> tuple[ArchiveObjectTag, SupportedObjectPayload]:
        """Read one archive handle and resolve its value when available."""
        handle, value = self.read_handle()
        return handle.tag, value

    def read_reference(self, *, resolve_new: bool = False) -> ArchiveObjectTag:
        """Read an object reference, optionally consuming a new inline object."""
        handle = self.session.read_object_handle()
        # A back-reference has no payload bytes. A new-object tag does, and the
        # caller must opt in when that field permits an inline definition.
        if resolve_new and handle.kind == "new_object":
            self.resolve(handle)
        return handle.tag

    def read_entity(self) -> EntityHeaderState:
        """Read the version-aware common entity prefix."""
        attribute_object_index = None
        owner_object_index = self.current_object_index

        def read_attribute_reference() -> ArchiveObjectTag:
            nonlocal attribute_object_index
            handle = self.session.read_object_handle()
            # Attribute containers may be declared at their first use. Consume
            # them now or the entity reader would continue in the nested body.
            if handle.kind == "new_object":
                self.resolve(handle)
            attribute_object_index = handle.object_index
            return handle.tag

        state = read_entity_header_body(
            self.session.reader,
            class_version=self.class_versions.get("CEntity", 0),
            read_reference=read_attribute_reference,
        )
        # EntityHeaderState is frozen; attach the resolved table index without
        # weakening that parser-state invariant.
        state = replace(
            state,
            attribute_container_object_index=attribute_object_index,
        )
        if owner_object_index is not None and attribute_object_index is not None and attribute_object_index > 0:
            self.session.attribute_container_indices_by_owner[owner_object_index] = attribute_object_index
        return state

    def read_drawing_element(self) -> DrawingElementState:
        """Read the common drawing-element prefix and unresolved references."""
        reader = self.session.reader
        start = reader.tell()
        # Serialized inheritance order is CEntity, material reference, then
        # CDrawingElement flags and layer reference.
        entity_header = self.read_entity()
        material_tag = self.read_reference(resolve_new=True)
        body = read_drawing_element_body(
            reader,
            self.class_versions.get("CDrawingElement", 9),
            self.read_reference,
        )
        # DrawingElementState is reused by every drawable entity. Assemble the
        # frozen base only after both inherited references and flags are read.
        return DrawingElementState(
            payload_start_offset=start,
            entity_header=entity_header,
            material_tag=material_tag,
            hidden=body[0],
            casts_shadows=body[1],
            receives_shadows=body[2],
            soft=body[3],
            smooth=body[4],
            locked=body[5],
            layer_tag=body[6],
            payload_end_offset=reader.tell(),
        )
