# SPDX-License-Identifier: MIT
"""Modern typed attribute-dictionary serialization."""

from __future__ import annotations

import math
import struct
from collections.abc import Iterable

from ..data_structure.model_metadata import (
    AttributeDictionary,
    AttributeDictionaryEntry,
)
from ..parser.tlv import TlvTag
from .tlv import encode_bool, encode_record, encode_records


def _encode_typed_value(entry: AttributeDictionaryEntry) -> bytes:
    if entry.value_type == 0:
        if not 0 <= entry.int_value <= 0xFFFFFFFF:
            raise ValueError("Attribute integer values must fit in u32")
        payload = encode_record(TlvTag.ATTR_TYPED_VALUE_INT, struct.pack("<I", entry.int_value))
    elif entry.value_type == 1:
        if not math.isfinite(entry.float_value):
            raise ValueError("Attribute float values must be finite")
        payload = encode_record(TlvTag.ATTR_TYPED_VALUE_F64, struct.pack("<d", entry.float_value))
    elif entry.value_type == 2:
        payload = encode_record(TlvTag.ATTR_TYPED_VALUE_BOOL, encode_bool(entry.bool_value))
    elif entry.value_type == 3:
        payload = encode_record(TlvTag.ATTR_TYPED_VALUE_STRING, entry.string_value.encode("utf-8"))
    elif entry.value_type == 4:
        if entry.nested_payload is None:
            raise ValueError("Nested attribute values require a payload")
        payload = encode_record(TlvTag.ATTR_TYPED_VALUE_NESTED, entry.nested_payload)
    else:
        raise ValueError(f"Unsupported attribute value type: {entry.value_type}")
    return encode_record(TlvTag.ATTR_TYPED_VALUE, payload)


def _encode_dictionary(dictionary: AttributeDictionary) -> bytes:
    if not dictionary.name:
        raise ValueError("Attribute dictionary names must not be empty")
    entries: list[tuple[int, bytes]] = []
    flags: list[tuple[int, bytes]] = []
    for entry in dictionary.entries:
        if not entry.key:
            raise ValueError("Attribute dictionary keys must not be empty")
        if not 0 <= entry.flags <= 0xFFFFFFFF:
            raise ValueError("Attribute entry flags must fit in u32")
        entries.extend(
            (
                (TlvTag.ATTR_DICT_ENTRY_KEY, entry.key.encode("utf-8")),
                (TlvTag.ATTR_TYPED_VALUE, _encode_typed_value(entry)[6:]),
            )
        )
        flags.append((TlvTag.ATTR_ENTRY_FLAGS, struct.pack("<I", entry.flags)))
    data = encode_records(
        [
            (TlvTag.ATTR_DICT_HEADER, b""),
            (TlvTag.ATTR_DICT_NAME, dictionary.name.encode("utf-8")),
            (TlvTag.ATTR_DICT_ENTRIES, encode_records(entries)),
            *flags,
        ]
    )
    return encode_record(
        TlvTag.ATTR_DICT_RECORD,
        encode_record(TlvTag.ATTR_DICT_DATA, data),
    )


def encode_attribute_dictionary_records(
    dictionaries: Iterable[AttributeDictionary],
) -> bytes:
    """Encode named dictionaries without their shared ``0x36B1`` root."""
    values = list(dictionaries)
    names = [dictionary.name for dictionary in values]
    if len(names) != len(set(names)):
        raise ValueError("Attribute dictionary names must be unique per owner")
    return b"".join(_encode_dictionary(dictionary) for dictionary in values)


def encode_attribute_dictionaries(
    dictionaries: Iterable[AttributeDictionary],
) -> bytes:
    """Encode a complete named attribute-dictionary root."""
    return encode_record(
        TlvTag.ATTR_DICTS_ROOT,
        encode_attribute_dictionary_records(dictionaries),
    )
