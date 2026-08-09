# SPDX-License-Identifier: MIT
"""Attribute dictionary normalization tests for modern TLV models."""

import struct

import pytest

from skppy.parser.attributes import parse_attribute_dictionaries
from skppy.parser.definitions import _parse_definition_attributes
from skppy.parser.entities import parse_entities

# These literal tags intentionally keep the fixture independent from TlvTag:
# 0x36B1-0x36B7 frame dictionaries, while 0x38A4/0x38A8-0x38AE frame values.


def _record(tag: int, payload: bytes) -> bytes:
    return struct.pack("<HI", tag, len(payload)) + payload


def _attribute_root(name: str = "TestData") -> bytes:
    entries = b"".join(
        (
            _record(0x36B6, b"Message"),
            _record(0x36B7, b"\x05"),
            _record(
                0x38A4,
                _record(0x38AD, b"Hello SketchUp"),
            ),
        )
    )
    data = b"".join(
        (
            _record(0x36B4, name.encode()),
            _record(0x36B5, entries),
        )
    )
    return _record(
        0x36B1,
        _record(0x36B2, _record(0x36B3, data)),
    )


def _entity_base(entity_id: int = 18) -> bytes:
    # 0x05DC wraps the 0x05DE ID and 0x05DD extended attribute payload.
    return _record(
        0x05DC,
        _record(0x05DE, bytes([entity_id])) + _record(0x05DD, _attribute_root()),
    )


def test_parse_modern_attribute_dictionary_preserves_entry_fields() -> None:
    dictionary = parse_attribute_dictionaries(_attribute_root())[0]

    assert dictionary.name == "TestData"
    assert len(dictionary.entries) == 1
    assert dictionary.entries[0].key == "Message"
    assert dictionary.entries[0].flags == 5
    assert dictionary.entries[0].value_type == 3
    assert dictionary.entries[0].string_value == "Hello SketchUp"


def test_parse_entities_maps_dictionary_to_owning_edge_id() -> None:
    edge = _record(
        0x0BB8,
        _record(0x07D0, _entity_base()) + _record(0x0BB9, b"\x01") + _record(0x0BBA, b"\x02"),
    )
    payload = _record(0x138A, edge)

    entities = parse_entities(payload)

    assert entities.edges[0].id == 18
    assert entities.attribute_dictionaries_by_entity_id[18][0].name == "TestData"


def test_definition_attributes_use_the_definition_entity_base() -> None:
    payload = _record(
        0x1388,
        _record(0x07D0, _entity_base()),
    )

    dictionaries = _parse_definition_attributes(payload)

    assert [dictionary.name for dictionary in dictionaries] == ["TestData"]


@pytest.mark.parametrize(
    ("value_record", "value_type", "field", "expected"),
    [
        (_record(0x38A8, b"\x2a"), 0, "int_value", 42),
        (
            _record(0x38A9, struct.pack("<d", 2.5)),
            1,
            "float_value",
            2.5,
        ),
        (_record(0x38AA, b"\x01"), 2, "bool_value", True),
        (
            _record(0x38AE, b"nested"),
            4,
            "nested_payload",
            b"nested",
        ),
    ],
)
def test_parse_modern_attribute_dictionary_decodes_typed_values(
    value_record: bytes,
    value_type: int,
    field: str,
    expected: object,
) -> None:
    """Normalize each supported modern typed value into shared entry fields."""
    entries = _record(0x36B6, b"Value") + _record(0x38A4, value_record)
    root = _record(
        0x36B1,
        _record(
            0x36B2,
            _record(
                0x36B3,
                _record(0x36B4, b"Types") + _record(0x36B5, entries),
            ),
        ),
    )

    entry = parse_attribute_dictionaries(root)[0].entries[0]

    assert entry.value_type == value_type
    assert getattr(entry, field) == expected
