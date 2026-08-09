# SPDX-License-Identifier: MIT
"""Raw SU2017 named attribute-dictionary writer fixtures."""

import math
import struct

import pytest

import skppy
from skppy.legacy_writter import build_legacy_2017_model


def _entry(key: str, value: str) -> skppy.AttributeDictionaryEntry:
    return skppy.AttributeDictionaryEntry(key=key, value_type=3, string_value=value)


def test_edge_dictionary_matches_raw_sdk_named_attribute_payload() -> None:
    model = skppy.Model.new()
    vertices = [model.entities.add_vertex(index, 0, 0) for index in range(2)]
    edge = model.entities.add_edge(*vertices)
    model.entities.attribute_dictionaries_by_entity_id[edge.id] = [
        skppy.AttributeDictionary(name="TestData", entries=[_entry("Message", "Hello SketchUp")])
    ]
    expected = bytes.fromhex("058000000000000000")
    expected += bytes.fromhex("fffeff0854006500730074004400610074006100")
    expected += bytes.fromhex("fffeff074d006500730073006100670065000a")
    expected += bytes.fromhex("fffeff0e480065006c006c006f00200053006b00650074006300680055007000")
    expected += bytes.fromhex("fffeff0000000000")

    encoded = build_legacy_2017_model(model)

    assert expected in encoded


def test_writes_dictionaries_for_model_resources_vertices_and_uv_faces() -> None:
    model = skppy.Model.new()
    material = model.add_material("Material")
    layer = model.add_layer("Layer")
    model.attribute_dictionaries = [skppy.AttributeDictionary(name="Model", entries=[_entry("A", "root")])]
    model.attribute_dictionaries_by_object_id[material.id] = [
        skppy.AttributeDictionary(name="MaterialData", entries=[_entry("A", "material")])
    ]
    model.attribute_dictionaries_by_object_id[layer.id] = [
        skppy.AttributeDictionary(name="LayerData", entries=[_entry("A", "layer")])
    ]
    face = model.entities.add_face([(0, 0, 0), (1, 0, 0), (0, 1, 0)])
    face.front_uv = skppy.FaceUVProjection()
    model.entities.attribute_dictionaries_by_entity_id[face.id] = [
        skppy.AttributeDictionary(name="FaceData", entries=[_entry("A", "face")])
    ]

    encoded = build_legacy_2017_model(model)

    for name in ("Model", "MaterialData", "LayerData", "FaceData"):
        assert name.encode("utf-16le") in encoded
    assert encoded.index("FaceData".encode("utf-16le")) < encoded.index(b"CFaceTextureCoords")


def test_writes_all_shared_attribute_value_types_and_flags() -> None:
    model = skppy.Model.new()
    entries = [
        skppy.AttributeDictionaryEntry(key="Integer", value_type=0, int_value=42),
        skppy.AttributeDictionaryEntry(key="Float", value_type=1, float_value=1.25),
        skppy.AttributeDictionaryEntry(key="Boolean", value_type=2, bool_value=True),
        skppy.AttributeDictionaryEntry(key="String", value_type=3, string_value="value", flags=7),
        skppy.AttributeDictionaryEntry(key="Nested", value_type=4, nested_payload=b"\x01\xfe"),
    ]
    model.attribute_dictionaries = [skppy.AttributeDictionary(name="Types", entries=entries)]

    encoded = build_legacy_2017_model(model)

    assert bytes((4,)) + struct.pack("<I", 42) in encoded
    assert bytes((6,)) + struct.pack("<d", 1.25) in encoded
    assert bytes((7, 1)) in encoded
    assert bytes((10,)) + bytes.fromhex("fffeff05760061006c0075006500") in encoded
    assert bytes((11,)) + struct.pack("<I", 2) + bytes((2, 1, 2, 0xFE)) in encoded
    assert "__skppy_flags__:String".encode("utf-16le") in encoded


@pytest.mark.parametrize(
    "dictionary, message",
    [
        (skppy.AttributeDictionary(), "names must not be empty"),
        (skppy.AttributeDictionary(name="D", entries=[_entry("", "x")]), "keys must not be empty"),
        (
            skppy.AttributeDictionary(name="D", entries=[skppy.AttributeDictionaryEntry(key="I", int_value=-1)]),
            "integer values must fit",
        ),
        (
            skppy.AttributeDictionary(
                name="D",
                entries=[skppy.AttributeDictionaryEntry(key="F", value_type=1, float_value=math.inf)],
            ),
            "float values must be finite",
        ),
        (
            skppy.AttributeDictionary(name="D", entries=[skppy.AttributeDictionaryEntry(key="N", value_type=4)]),
            "require a payload",
        ),
        (
            skppy.AttributeDictionary(name="D", entries=[skppy.AttributeDictionaryEntry(key="X", value_type=99)]),
            "Unsupported legacy attribute value type",
        ),
    ],
)
def test_rejects_invalid_legacy_attributes(dictionary: skppy.AttributeDictionary, message: str) -> None:
    model = skppy.Model.new()
    model.attribute_dictionaries = [dictionary]

    with pytest.raises(ValueError, match=message):
        build_legacy_2017_model(model)
