# SPDX-License-Identifier: MIT
"""Parse shared attribute dictionaries from modern TLV containers."""

from __future__ import annotations

from ..data_structure.model_metadata import (
    AttributeDictionary,
    AttributeDictionaryEntry,
)
from .tlv import (
    TlvTag,
    find_child,
    index_children,
    iter_records,
    read_bool,
    read_compact_int,
    read_f64_le,
    read_utf8,
)


def parse_attribute_dictionaries(container_payload: bytes) -> list[AttributeDictionary]:
    """Parse the attribute root nested in a model or entity container."""
    root = find_child(container_payload, TlvTag.ATTR_DICTS_ROOT)
    return parse_attribute_dictionary_root(root) if root is not None else []


def parse_entity_attribute_dictionaries(
    entity_base_payload: bytes,
) -> list[AttributeDictionary]:
    """Parse named dictionaries from an entity's extended ID payload."""
    id_wrapper = find_child(entity_base_payload, TlvTag.ID_WRAPPER)
    if id_wrapper is None:
        return []
    extended = find_child(id_wrapper, TlvTag.ID_EXT_PAYLOAD)
    return parse_attribute_dictionaries(extended) if extended is not None else []


def parse_attribute_dictionary_root(root_payload: bytes) -> list[AttributeDictionary]:
    """Parse all named dictionary records inside a ``0x36B1`` root."""
    dictionaries: list[AttributeDictionary] = []
    for tag, record in iter_records(root_payload):
        if tag != TlvTag.ATTR_DICT_RECORD:
            continue
        data = index_children(record).get(TlvTag.ATTR_DICT_DATA)
        if data is None:
            # Technical records such as face UV projections share this root.
            continue
        fields = index_children(data)
        dictionary = AttributeDictionary()
        name_payload = fields.get(TlvTag.ATTR_DICT_NAME)
        if name_payload is not None:
            dictionary.name = read_utf8(name_payload)
        entries = fields.get(TlvTag.ATTR_DICT_ENTRIES)
        if entries is not None:
            dictionary.entries = _parse_entries(entries)
        dictionaries.append(dictionary)
    return dictionaries


def _parse_entries(payload: bytes) -> list[AttributeDictionaryEntry]:
    """Pair flat key/flags/value records into shared typed entries."""
    entries: list[AttributeDictionaryEntry] = []
    current_key = ""
    current_flags = 0
    for tag, value in iter_records(payload):
        if tag == TlvTag.ATTR_DICT_ENTRY_KEY:
            current_key = read_utf8(value) if value else ""
            current_flags = 0
        elif tag == TlvTag.ATTR_ENTRY_FLAGS:
            current_flags = read_compact_int(value) if value else 0
        elif tag == TlvTag.ATTR_TYPED_VALUE:
            entries.append(_parse_typed_entry(current_key, current_flags, value))
    return entries


def _parse_typed_entry(
    key: str,
    flags: int,
    payload: bytes,
) -> AttributeDictionaryEntry:
    """Decode the first supported payload selected by a typed-value record."""
    entry = AttributeDictionaryEntry()
    entry.key = key
    entry.flags = flags
    fields = index_children(payload)
    string_payload = fields.get(TlvTag.ATTR_TYPED_VALUE_STRING)
    if string_payload is not None:
        entry.value_type = 3
        entry.string_value = read_utf8(string_payload)
        return entry
    bool_payload = fields.get(TlvTag.ATTR_TYPED_VALUE_BOOL)
    if bool_payload is not None:
        entry.value_type = 2
        entry.bool_value = read_bool(bool_payload)
        return entry
    float_payload = fields.get(TlvTag.ATTR_TYPED_VALUE_F64)
    if float_payload is not None:
        entry.value_type = 1
        entry.float_value = read_f64_le(float_payload)
        return entry
    int_payload = fields.get(TlvTag.ATTR_TYPED_VALUE_INT)
    if int_payload is not None:
        entry.value_type = 0
        entry.int_value = read_compact_int(int_payload)
        return entry
    nested_payload = fields.get(TlvTag.ATTR_TYPED_VALUE_NESTED)
    if nested_payload is not None:
        entry.value_type = 4
        entry.nested_payload = nested_payload
    return entry
