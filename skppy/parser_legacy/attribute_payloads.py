# SPDX-License-Identifier: MIT
"""Shared attribute payload decoding for legacy SketchUp archives."""

from __future__ import annotations

from collections.abc import Callable
from typing import BinaryIO

from ..data_structure.model_metadata import (
    AttributeDictionary,
    AttributeDictionaryEntry,
)

from .parser_types import AttributeContainerPayload
from .binary import ArchiveObjectTag, LegacyArchiveReader
from .options_payloads import read_typed_value


def read_named_attribute_body(
    stream: BinaryIO,
    *,
    class_version: int,
) -> AttributeDictionary:
    """Read a ``CAttributeNamed`` body after its entity header."""
    reader = LegacyArchiveReader(stream)
    reader.read_u32()
    name = reader.read_legacy_utf16_string("attribute name")
    entries: list[AttributeDictionaryEntry] = []

    while True:
        key = reader.read_legacy_utf16_string("attribute key")
        if not key:
            break
        entries.append(attribute_dictionary_entry(key, read_typed_value(stream)))

    if class_version > 0:
        reader.read_u32()
    return AttributeDictionary(name=name, entries=_restore_entry_flags(entries))


def _restore_entry_flags(entries: list[AttributeDictionaryEntry]) -> list[AttributeDictionaryEntry]:
    prefix = "__skppy_flags__:"
    flags = {entry.key.removeprefix(prefix): entry.int_value for entry in entries if entry.key.startswith(prefix)}
    values = [entry for entry in entries if not entry.key.startswith(prefix)]
    for entry in values:
        entry.flags = flags.get(entry.key, 0)
    return values


def read_attribute_container_body(
    reader: LegacyArchiveReader,
    *,
    object_tag: ArchiveObjectTag,
    payload_start_offset: int,
    read_entry: Callable[[], tuple[ArchiveObjectTag, object]],
) -> AttributeContainerPayload:
    """Read attribute-container entries after its entity header.

    Containers also own technical objects such as ``CFaceTextureCoords``.
    Keep every entry tag even though only named dictionaries are exposed as
    model metadata; face readers use those tags to recover UV projections.
    """
    tags: list[ArchiveObjectTag] = []
    dictionaries: list[AttributeDictionary] = []
    while True:
        tag, value = read_entry()
        if tag.kind == "null":
            return (
                object_tag,
                tuple(tags),
                tuple(dictionaries),
                payload_start_offset,
                reader.tell(),
            )
        tags.append(tag)
        if isinstance(value, AttributeDictionary):
            dictionaries.append(value)


def attribute_dictionary_entry(key: str, value: object) -> AttributeDictionaryEntry:
    """Map a native legacy typed value to the shared attribute representation."""
    entry = AttributeDictionaryEntry(key=key)
    if isinstance(value, bool):
        entry.value_type = 2
        entry.bool_value = value
    elif isinstance(value, int):
        entry.value_type = 0
        entry.int_value = value
    elif isinstance(value, float):
        entry.value_type = 1
        entry.float_value = value
    elif isinstance(value, str):
        entry.value_type = 3
        entry.string_value = value
    elif isinstance(value, tuple) and all(isinstance(item, int) and 0 <= item <= 255 for item in value):
        entry.value_type = 4
        entry.nested_payload = bytes(value)
    else:
        entry.value_type = 4
        entry.nested_payload = repr(value).encode("utf-8")
    return entry
