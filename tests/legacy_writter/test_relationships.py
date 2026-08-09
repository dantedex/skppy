# SPDX-License-Identifier: MIT
"""Raw SU2017 entity-relationship writer fixtures."""

import pytest

import skppy
from skppy.legacy_writter import build_legacy_2017_model


def test_relationship_matches_raw_carchive_object_and_entity_references() -> None:
    model = skppy.Model.new()
    start = model.entities.add_vertex(0, 0, 0)
    end = model.entities.add_vertex(1, 0, 0)
    edge = model.entities.add_edge(start, end)
    model.entities.relationships.append(skppy.EntityRelationship(start.id, edge.id))
    expected = bytes.fromhex("ffff00000d004352656c6174696f6e73686970000001150e000c00")

    encoded = build_legacy_2017_model(model)

    assert expected in encoded


def test_writes_relationships_inside_component_definition_scope() -> None:
    model = skppy.Model.new()
    definition = model.add_definition("Related")
    start = definition.entities.add_vertex(0, 0, 0)
    end = definition.entities.add_vertex(1, 0, 0)
    edge = definition.entities.add_edge(start, end)
    definition.entities.relationships.append(skppy.EntityRelationship(edge.id, end.id))

    encoded = build_legacy_2017_model(model)

    assert encoded.count(b"CRelationship") == 1


@pytest.mark.parametrize(
    "relationship, message",
    [
        (skppy.EntityRelationship(None, 1), "require source and target"),
        (skppy.EntityRelationship(1, 99), "missing entity IDs 1, 99"),
    ],
)
def test_rejects_incomplete_relationships(relationship: skppy.EntityRelationship, message: str) -> None:
    model = skppy.Model.new()
    model.entities.add_vertex(0, 0, 0)
    model.entities.relationships.append(relationship)

    with pytest.raises(ValueError, match=message):
        build_legacy_2017_model(model)
