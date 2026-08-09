# SPDX-License-Identifier: MIT
"""Raw SU2017 component-definition and placement writer fixtures."""

import struct

import pytest

import skppy
from skppy.legacy_writter import build_legacy_2017_model
from skppy.legacy_writter.model import _LegacyGeometryEncoder


def test_writes_definition_and_instance_as_native_carchive_objects() -> None:
    model = skppy.Model.new()
    definition = model.add_definition("Probe")
    definition.guid = bytes(range(16))
    definition.description = "Native"
    definition.entities.add_edge(definition.entities.add_vertex(0, 0, 0), definition.entities.add_vertex(1, 0, 0))
    instance = model.entities.add_instance(definition, skppy.Transform.from_translation(10, 20, 30), name="Placed")
    instance.guid = bytes(range(16, 32))

    encoded = build_legacy_2017_model(model)

    assert bytes.fromhex("ffff0b00140043436f6d706f6e656e74446566696e6974696f6e") in encoded
    assert bytes.fromhex("ffff0600120043436f6d706f6e656e74496e7374616e6365") in encoded
    assert bytes(range(16)) + bytes.fromhex("fffeff05500072006f0062006500") in encoded
    assert struct.pack("<3d", 10, 20, 30) in encoded
    assert bytes(range(16, 32)) in encoded


def test_writes_groups_and_images_with_their_native_runtime_classes() -> None:
    model = skppy.Model.new()
    group_definition = model.add_definition("Group Definition")
    image_definition = model.add_definition("Image Definition")
    model.entities.groups.append(skppy.Group(id=1, name="Group", definition_id=group_definition.id))
    model.entities.images.append(skppy.Image(id=2, name="Image", definition_id=image_definition.id))

    encoded = build_legacy_2017_model(model)

    assert bytes.fromhex("ffff010006004347726f7570") in encoded
    assert bytes.fromhex("ffff0100060043496d616765") in encoded


def test_writes_component_behavior_fields_in_wire_order() -> None:
    model = skppy.Model.new()
    definition = model.add_definition("Behavior")
    definition.behavior_snap_enabled = True
    definition.behavior_cuts_opening = True
    definition.behavior_snap_mode = 2
    definition.behavior_always_face_camera = True
    definition.behavior_shadows_face_sun = True
    definition.behavior_no_scale_mask = 7

    encoded = build_legacy_2017_model(model)

    assert bytes.fromhex("0000000101020000000307000000000000000000") in encoded


def test_rejects_missing_and_cyclic_component_definitions() -> None:
    missing = skppy.Model.new()
    missing.entities.component_instances.append(skppy.ComponentInstance(definition_id=99))
    with pytest.raises(ValueError, match="missing definition ID 99"):
        build_legacy_2017_model(missing)

    cyclic = skppy.Model.new()
    first = cyclic.add_definition("First")
    second = cyclic.add_definition("Second")
    first.entities.add_instance(second)
    second.entities.add_instance(first)
    with pytest.raises(ValueError, match="component cycle"):
        build_legacy_2017_model(cyclic)

    nested_missing = skppy.Model.new()
    parent = nested_missing.add_definition("Parent")
    parent.entities.component_instances.append(skppy.ComponentInstance(definition_id=99))
    with pytest.raises(ValueError, match="missing definition ID 99"):
        build_legacy_2017_model(nested_missing)


def test_orders_shared_dependencies_once_and_rejects_placements_without_model_context() -> None:
    model = skppy.Model.new()
    dependency = model.add_definition("Dependency")
    first = model.add_definition("First")
    second = model.add_definition("Second")
    first.entities.add_instance(dependency)
    second.entities.add_instance(dependency)

    encoded = build_legacy_2017_model(model)

    assert encoded.count("Dependency".encode("utf-16le")) == 1

    standalone = skppy.Entities(component_instances=[skppy.ComponentInstance(definition_id=1)])
    with pytest.raises(NotImplementedError, match="model-level legacy encoder"):
        _LegacyGeometryEncoder(standalone).encode()
