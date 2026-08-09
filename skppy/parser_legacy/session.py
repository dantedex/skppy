# SPDX-License-Identifier: MIT
"""Stateful object and reference tracking for legacy CArchive streams."""

from __future__ import annotations

from typing import BinaryIO

from .parser_types import EdgeState, SupportedObjectPayload
from .binary import (
    ArchiveIndexTable,
    ArchiveObjectHandle,
    ArchiveObjectRegistration,
    LegacyArchiveReader,
)


class LegacyArchiveSession:
    """Stateful CArchive reader with shared class/object index tracking."""

    def __init__(self, stream: BinaryIO, *, file_version: str = "unknown") -> None:
        """Create a session for one old-format archive stream."""
        self.reader = LegacyArchiveReader(stream)
        self.file_version = file_version
        self.index_table = ArchiveIndexTable()
        self.objects: dict[int, SupportedObjectPayload] = {}
        self._object_history: list[SupportedObjectPayload] = []
        self.attribute_container_indices_by_owner: dict[int, int] = {}
        self.last_edge: EdgeState | None = None

    def tell(self) -> int:
        """Return the current stream offset."""
        return self.reader.tell()

    def register_implicit_object(self, class_name: str, schema: int | None = None) -> ArchiveObjectRegistration:
        """Register a root-like object whose tag is implicit in the stream."""
        return self.index_table.register_implicit_object(class_name, schema)

    def read_object_handle(self) -> ArchiveObjectHandle:
        """Read an object tag and resolve/register it in archive-table order."""
        # Registration happens before body decoding because nested objects must
        # receive indices after their parent, exactly as CArchive does.
        return self.index_table.resolve_or_register_object_tag(self.reader.read_object_tag())

    def store_object(self, object_index: int, value: SupportedObjectPayload) -> None:
        """Store a newly decoded object while preserving insertion order."""
        # Back-reference resolution may revisit an index; history records first
        # completion only so component checkpoints cannot duplicate children.
        if object_index not in self.objects:
            self._object_history.append(value)
        self.objects[object_index] = value

    def object_checkpoint(self) -> int:
        """Return a checkpoint for collecting subsequently decoded objects."""
        return len(self._object_history)

    def objects_since(self, checkpoint: int) -> list[SupportedObjectPayload]:
        """Return objects first stored after *checkpoint* in decoding order."""
        return self._object_history[checkpoint:]

    @property
    def stream(self) -> BinaryIO:
        """Return the underlying binary stream."""
        return self.reader.stream
