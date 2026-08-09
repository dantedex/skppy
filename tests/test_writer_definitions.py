# SPDX-License-Identifier: MIT
"""Tests for component definition, instance, and group serialization."""

from __future__ import annotations

import struct

import pytest

from skppy import Transform, new_model
from skppy.data_structure.entities import ComponentDefinition, ComponentInstance
from skppy.writer.definitions import encode_definitions
from skppy.writer.model_data import encode_model_data


def _raw_record(tag: int, payload: bytes = b"") -> bytes:
    """Construct expected wire bytes without writer helpers."""
    return struct.pack("<HI", tag, len(payload)) + payload


def test_nested_definitions_instances_and_groups_match_raw_records() -> None:
    """Keep nested references, transforms, GUIDs, and group semantics."""
    model = new_model()
    leaf = model.add_definition("Leaf", description="Geometry definition")
    leaf.entities.add_face([(0, 0, 0), (1, 0, 0), (0, 1, 0)])
    parent = model.add_definition("Parent")
    nested = parent.entities.add_instance(leaf, name="Nested leaf")
    _group_definition, group = model.add_group("Cluster", Transform.from_translation(4.0, 5.0, 6.0))
    root_instance = model.entities.add_instance(parent, Transform.from_translation(1.0, 2.0, 3.0), name="Root parent")
    encoded = encode_model_data(model)

    assert _raw_record(0x157E, b"Leaf") in encoded
    assert _raw_record(0x157E, b"Parent") in encoded
    assert _raw_record(0x157E, b"Cluster") in encoded
    assert _raw_record(0x157F, b"Geometry definition") in encoded
    assert _raw_record(0x1965, b"Nested leaf") in encoded
    assert _raw_record(0x1967, b"\x12") in encoded
    assert _raw_record(0x1968, nested.guid) in encoded
    assert _raw_record(0x1965, b"Root parent") in encoded
    assert _raw_record(0x1967, b"\x13") in encoded
    assert _raw_record(0x1968, root_instance.guid) in encoded
    assert _raw_record(0x1966, struct.pack("<13d", *root_instance.transform)) in encoded
    assert _raw_record(0x1967, b"\x14") in encoded
    assert _raw_record(0x1968, group.guid) in encoded
    assert _raw_record(0x1966, struct.pack("<13d", *group.transform)) in encoded


def test_unknown_instance_definition_is_rejected() -> None:
    """Do not serialize instances whose definition is absent from the model."""
    model = new_model()
    model.entities.component_instances.append(ComponentInstance(id=1, definition_id=99))
    with pytest.raises(ValueError, match="definition ID mapping"):
        encode_model_data(model)


def _encode_definition_direct(
    definitions: list[ComponentDefinition],
    *,
    definition_id_map: dict[int, int] | None = None,
    entity_id_maps: dict[int, dict[int, int]] | None = None,
) -> bytes:
    ids = [definition.id for definition in definitions]
    return encode_definitions(
        definitions,
        definition_id_map=(
            {definition_id: 18 + index for index, definition_id in enumerate(ids)}
            if definition_id_map is None
            else definition_id_map
        ),
        entity_id_maps=({definition_id: {} for definition_id in ids} if entity_id_maps is None else entity_id_maps),
        material_id_map={},
        layer_id_map={},
        attribute_dictionaries_by_object_id={},
    )


def test_definition_packed_payload_matches_raw_record() -> None:
    definition = ComponentDefinition(id=1, name="Packed", packed_payload=b"raw")
    assert _raw_record(0x1585, b"raw") in _encode_definition_direct([definition])


@pytest.mark.parametrize(
    ("definitions", "message"),
    [
        ([ComponentDefinition(id=0, name="A")], "IDs must be positive and unique"),
        (
            [ComponentDefinition(id=1, name="A"), ComponentDefinition(id=1, name="B")],
            "IDs must be positive and unique",
        ),
        ([ComponentDefinition(id=1, name="")], "names must be non-empty and unique"),
        (
            [ComponentDefinition(id=1, name="A"), ComponentDefinition(id=2, name="A")],
            "names must be non-empty and unique",
        ),
        (
            [ComponentDefinition(id=1, name="A", guid=b"short")],
            "GUID must contain 16 bytes",
        ),
        (
            [ComponentDefinition(id=1, name="A", timestamp=-1)],
            "integer fields must fit in u32",
        ),
    ],
)
def test_definitions_reject_invalid_identity_and_scalars(definitions: list[ComponentDefinition], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _encode_definition_direct(definitions)


def test_definition_maps_must_cover_every_definition() -> None:
    definition = ComponentDefinition(id=1, name="A")
    with pytest.raises(ValueError, match="ID map does not cover"):
        _encode_definition_direct([definition], definition_id_map={})
    with pytest.raises(ValueError, match="Entity ID maps do not cover"):
        _encode_definition_direct([definition], entity_id_maps={})
