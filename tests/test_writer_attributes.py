# SPDX-License-Identifier: MIT
"""Raw-byte checks for modern attribute dictionary serialization."""

from __future__ import annotations

import struct

import pytest

from skppy.data_structure.entities import Edge, Vertex
from skppy.data_structure.model import Model
from skppy.data_structure.model_metadata import (
    AttributeDictionary,
    AttributeDictionaryEntry,
)
from skppy.data_structure.primitives import Vector3D
from skppy.writer.attributes import (
    _encode_typed_value,
    encode_attribute_dictionaries,
    encode_attribute_dictionary_records,
)
from skppy.writer.model_data import encode_model_data


def _raw_record(tag: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HI", tag, len(payload)) + payload


def _string_dictionary(name: str, key: str, value: str) -> AttributeDictionary:
    return AttributeDictionary(
        name=name,
        entries=[
            AttributeDictionaryEntry(
                key=key,
                value_type=3,
                string_value=value,
            )
        ],
    )


def _raw_string_dictionary_extension(name: str, key: str, value: str) -> bytes:
    entries = _raw_record(0x36B6, key.encode()) + _raw_record(0x38A4, _raw_record(0x38AD, value.encode()))
    data = b"".join(
        (
            _raw_record(0x36B0),
            _raw_record(0x36B4, name.encode()),
            _raw_record(0x36B5, entries),
            _raw_record(0x36B7, struct.pack("<I", 0)),
        )
    )
    return _raw_record(
        0x05DD,
        _raw_record(0x36B1, _raw_record(0x36B2, _raw_record(0x36B3, data))),
    )


def test_string_dictionary_matches_raw_expected_bytes() -> None:
    entries = b"".join(
        (
            _raw_record(0x36B6, b"Message"),
            _raw_record(0x38A4, _raw_record(0x38AD, b"Hello SketchUp")),
        )
    )
    data = b"".join(
        (
            _raw_record(0x36B0),
            _raw_record(0x36B4, b"TestData"),
            _raw_record(0x36B5, entries),
            _raw_record(0x36B7, struct.pack("<I", 0)),
        )
    )
    expected = _raw_record(
        0x36B1,
        _raw_record(0x36B2, _raw_record(0x36B3, data)),
    )
    dictionary = _string_dictionary("TestData", "Message", "Hello SketchUp")

    assert encode_attribute_dictionaries([dictionary]) == expected


def test_edge_dictionary_is_embedded_in_its_raw_id_extension() -> None:
    model = Model.new()
    model.entities.vertices = [
        Vertex(1, Vector3D(0, 0, 0)),
        Vertex(2, Vector3D(10, 10, 10)),
    ]
    model.entities.edges = [Edge(3, 1, 2)]
    model.entities.attribute_dictionaries_by_entity_id[3] = [
        _string_dictionary("TestData", "Message", "Hello SketchUp")
    ]
    model.entities.attribute_dictionaries_by_entity_id[1] = [_string_dictionary("VertexData", "Role", "start")]

    encoded = encode_model_data(model)

    expected_value = _raw_record(0x38AD, b"Hello SketchUp")
    assert expected_value in encoded
    assert _raw_string_dictionary_extension("VertexData", "Role", "start") in encoded


def test_definition_dictionary_is_embedded_in_its_raw_scope_id() -> None:
    model = Model.new()
    definition = model.add_definition("DynamicComponent")
    model.attribute_dictionaries_by_object_id[definition.id] = [
        _string_dictionary("dynamic_attributes", "_lenx_nominal", "100")
    ]

    encoded = encode_model_data(model)

    assert _raw_record(0x36B4, b"dynamic_attributes") in encoded
    assert _raw_record(0x38AD, b"100") in encoded


def test_model_dictionary_is_wrapped_in_raw_root_scope_extension() -> None:
    model = Model.new()
    model.attribute_dictionaries = [_string_dictionary("ModelData", "Author", "skppy")]

    encoded = encode_model_data(model)

    entries = b"".join(
        (
            _raw_record(0x36B6, b"Author"),
            _raw_record(0x38A4, _raw_record(0x38AD, b"skppy")),
        )
    )
    dictionary = _raw_record(
        0x36B2,
        _raw_record(
            0x36B3,
            _raw_record(0x36B0)
            + _raw_record(0x36B4, b"ModelData")
            + _raw_record(0x36B5, entries)
            + _raw_record(0x36B7, struct.pack("<I", 0)),
        ),
    )
    extension = _raw_record(0x05DD, _raw_record(0x36B1, dictionary))
    entity_base = _raw_record(
        0x07D0,
        _raw_record(0x05DC, extension) + _raw_record(0x07D3, b"\x06"),
    )
    assert entity_base in encoded


def test_material_and_layer_dictionaries_use_raw_id_extensions() -> None:
    model = Model.new()
    material = model.add_material("AttributedMaterial")
    layer = model.add_layer("AttributedLayer")
    model.attribute_dictionaries_by_object_id[material.id] = [_string_dictionary("MaterialData", "Kind", "paint")]
    model.attribute_dictionaries_by_object_id[layer.id] = [
        _string_dictionary("LayerData", "Discipline", "architecture")
    ]

    encoded = encode_model_data(model)

    material_extension = _raw_record(
        0x05DD,
        _raw_record(
            0x36B1,
            _raw_record(
                0x36B2,
                _raw_record(
                    0x36B3,
                    _raw_record(0x36B0)
                    + _raw_record(0x36B4, b"MaterialData")
                    + _raw_record(
                        0x36B5,
                        _raw_record(0x36B6, b"Kind") + _raw_record(0x38A4, _raw_record(0x38AD, b"paint")),
                    )
                    + _raw_record(0x36B7, struct.pack("<I", 0)),
                ),
            ),
        ),
    )
    assert material_extension in encoded
    assert _raw_record(0x36B4, b"LayerData") in encoded
    assert _raw_record(0x38AD, b"architecture") in encoded


@pytest.mark.parametrize(
    ("entry", "expected_payload"),
    [
        (
            AttributeDictionaryEntry(key="i", value_type=0, int_value=42),
            _raw_record(0x38A8, struct.pack("<I", 42)),
        ),
        (
            AttributeDictionaryEntry(key="f", value_type=1, float_value=1.25),
            _raw_record(0x38A9, struct.pack("<d", 1.25)),
        ),
        (
            AttributeDictionaryEntry(key="b", value_type=2, bool_value=True),
            _raw_record(0x38AA, b"\x01"),
        ),
        (
            AttributeDictionaryEntry(key="n", value_type=4, nested_payload=b"raw"),
            _raw_record(0x38AE, b"raw"),
        ),
    ],
)
def test_attribute_scalar_types_match_raw_expected_bytes(
    entry: AttributeDictionaryEntry,
    expected_payload: bytes,
) -> None:
    assert _encode_typed_value(entry) == _raw_record(0x38A4, expected_payload)


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        (
            AttributeDictionaryEntry(key="x", value_type=0, int_value=-1),
            "fit in u32",
        ),
        (
            AttributeDictionaryEntry(key="x", value_type=1, float_value=float("nan")),
            "must be finite",
        ),
        (
            AttributeDictionaryEntry(key="x", value_type=4),
            "require a payload",
        ),
        (
            AttributeDictionaryEntry(key="x", value_type=99),
            "Unsupported",
        ),
    ],
)
def test_attribute_values_reject_invalid_wire_values(
    entry: AttributeDictionaryEntry,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _encode_typed_value(entry)


@pytest.mark.parametrize(
    ("dictionary", "message"),
    [
        (AttributeDictionary(name=""), "names must not be empty"),
        (
            AttributeDictionary(
                name="Data",
                entries=[AttributeDictionaryEntry(key="", value_type=3)],
            ),
            "keys must not be empty",
        ),
        (
            AttributeDictionary(
                name="Data",
                entries=[AttributeDictionaryEntry(key="x", flags=-1)],
            ),
            "flags must fit in u32",
        ),
    ],
)
def test_attribute_dictionaries_reject_invalid_names_keys_and_flags(
    dictionary: AttributeDictionary,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        encode_attribute_dictionary_records([dictionary])


def test_attribute_dictionary_names_are_unique_per_owner() -> None:
    dictionary = AttributeDictionary(name="Data")
    with pytest.raises(ValueError, match="must be unique"):
        encode_attribute_dictionary_records([dictionary, dictionary])
