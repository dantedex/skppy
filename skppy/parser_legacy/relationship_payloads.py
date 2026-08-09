# SPDX-License-Identifier: MIT
"""Relationship payload decoding for legacy component graphs."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeGuard

from .parser_types import RelationshipCollection, RelationshipReferences
from .binary import ArchiveObjectTag, LegacyArchiveReader
from .read_context import ObjectReadContext


def read_relationship(context: ObjectReadContext) -> RelationshipReferences:
    """Read one relationship after its common entity prefix."""
    context.read_entity()
    return read_relationship_body(context.read_reference)


def read_relationship_map(context: ObjectReadContext, *, class_version: int) -> RelationshipCollection:
    """Read and resolve a collection of component relationships."""
    return read_relationship_map_body(
        context.session.reader,
        class_version=class_version,
        read_object=lambda: context.read_object()[1],
    )


def read_relationship_body(
    read_reference: Callable[[], ArchiveObjectTag],
) -> RelationshipReferences:
    """Read source and target references after a relationship entity header."""
    return read_reference(), read_reference()


def read_relationship_map_body(
    reader: LegacyArchiveReader,
    *,
    class_version: int,
    read_object: Callable[[], object],
) -> RelationshipCollection:
    """Read a relationship map and retain confirmed reference pairs."""
    if class_version != 0:
        raise NotImplementedError("Only SketchUp 8 CRelationshipMap version 0 is decoded.")
    count = reader.read_u32()
    relationships: list[RelationshipReferences] = []
    for _ in range(count):
        value = read_object()
        if _is_relationship(value):
            relationships.append(value)
    return tuple(relationships)


def _is_relationship(value: object) -> TypeGuard[RelationshipReferences]:
    return isinstance(value, tuple) and len(value) == 2 and all(isinstance(item, ArchiveObjectTag) for item in value)
