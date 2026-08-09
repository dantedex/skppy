# SPDX-License-Identifier: MIT
"""Raw SU2017 linear- and radial-dimension writer fixtures."""

import math

import pytest

import skppy
from skppy.legacy_writter import build_legacy_2017_model
from skppy.legacy_writter.model import _LegacyGeometryEncoder


def test_linear_dimension_matches_raw_carchive_payload() -> None:
    entities = skppy.Entities()
    entities.linear_dimensions.append(
        skppy.LinearDimension(
            id=1,
            text="Length",
            arrow_type=3,
            start=skppy.PointReference(kind=1, position=skppy.Vector3D(1, 2, 3)),
            end=skppy.PointReference(kind=1, position=skppy.Vector3D(4, 5, 6)),
            direction=skppy.Vector3D(0, 0, 1),
            render_direction=skppy.Vector3D(1, 0, 0),
            mode=2,
            offset=2.5,
            line_position=1.5,
            alignment=1,
        )
    )
    expected = bytes.fromhex(
        "01000000ffff060010004344696d656e73696f6e4c696e6561720000011200000001010000000000fffeff064c0065006e00670074006800ffff0100"
        "070043536b466f6e7400000113fffeff0541007200690061006c0000000c00000000000000000000f03f000300000001000000040000000000000000"
        "00f03f000000000000004000000000000008400000000000000000000000000100000004000000000000000000104000000000000014400000000000"
        "00184000000000000000000000000000000000000000000000000000000000000000000000f03f000000000000f03f00000000000000000000000000"
        "000000020000000000000000000440000000000000f83f01000000000000000000"
    )

    assert _LegacyGeometryEncoder(entities).encode() == expected


def test_writes_associated_radial_dimension_and_nested_linear_paths() -> None:
    model = skppy.Model.new()
    definition = model.add_definition("Reference")
    nested_edge = definition.entities.add_edge(
        definition.entities.add_vertex(0, 0, 0),
        definition.entities.add_vertex(1, 0, 0),
    )
    instance = model.entities.add_instance(definition)
    root_edge = model.entities.add_edge(model.entities.add_vertex(0, 0, 0), model.entities.add_vertex(1, 0, 0))
    model.entities.linear_dimensions.append(
        skppy.LinearDimension(
            id=10,
            start=skppy.PointReference(entity_id=nested_edge.id, instance_path_ids=[instance.id]),
            end=skppy.PointReference(entity_id=root_edge.id),
        )
    )
    model.entities.radial_dimensions.append(skppy.RadialDimension(id=11, target_entity_id=root_edge.id))

    encoded = build_legacy_2017_model(model)

    assert encoded.count(b"CDimensionLinear") == 1
    assert encoded.count(b"CDimensionRadial") == 1


def test_rejects_invalid_dimension_reference_graphs() -> None:
    missing_leaf = skppy.Entities(linear_dimensions=[skppy.LinearDimension(start=skppy.PointReference(entity_id=99))])
    with pytest.raises(ValueError, match="leaf references missing entity ID 99"):
        _LegacyGeometryEncoder(missing_leaf).encode()

    non_placement = skppy.Entities()
    edge = non_placement.add_edge(non_placement.add_vertex(0, 0, 0), non_placement.add_vertex(1, 0, 0))
    non_placement.linear_dimensions.append(
        skppy.LinearDimension(start=skppy.PointReference(instance_path_ids=[edge.id]))
    )
    with pytest.raises(ValueError, match="is not a component placement"):
        _LegacyGeometryEncoder(non_placement).encode()

    unavailable = _LegacyGeometryEncoder(skppy.Entities())
    unavailable.entities.component_instances.append(skppy.ComponentInstance(id=1, definition_id=99))
    unavailable.entity_indices[1] = 12
    with pytest.raises(ValueError, match="unavailable definition ID 99"):
        unavailable._resolve_point_reference(None, [1])

    with pytest.raises(ValueError, match="missing placement ID 99"):
        unavailable._resolve_point_reference(None, [99])


def test_rejects_missing_radial_targets_and_embedded_arcs() -> None:
    associated = skppy.Entities(radial_dimensions=[skppy.RadialDimension(id=1, target_entity_id=99)])
    with pytest.raises(ValueError, match="radial-dimension target references missing entity ID 99"):
        _LegacyGeometryEncoder(associated).encode()

    model = skppy.Model.new()
    model.entities.radial_dimensions.append(skppy.RadialDimension(id=1))
    with pytest.raises(ValueError, match="require embedded arc geometry"):
        build_legacy_2017_model(model)

    with pytest.raises(ValueError, match="require embedded arc geometry"):
        _LegacyGeometryEncoder(skppy.Entities())._write_embedded_arc(None)


def test_unassociated_radial_dimension_matches_raw_carchive_payload() -> None:
    entities = skppy.Entities()
    entities.radial_dimensions.append(
        skppy.RadialDimension(
            id=1,
            text="Radius",
            parameter=0.5,
            radius_ratio=2.0,
            is_diameter=True,
            arc=skppy.ArcGeometry(
                center=skppy.Vector3D(1, 2, 3),
                normal=skppy.Vector3D(0, 0, 1),
                x_axis=skppy.Vector3D(10, 0, 0),
                start_angle=0.0,
                end_angle=math.pi / 2,
                y_axis=skppy.Vector3D(0, 10, 0),
            ),
        )
    )
    expected = bytes.fromhex(
        "01000000ffff020010004344696d656e73696f6e52616469616c0000011200000001010000000000fffeff065200610064"
        "00690075007300ffff0100070043536b466f6e7400000113fffeff0541007200690061006c0000000c0000000000000000"
        "0000f03f00000000000000000000000000e03f000000000000004001000000000000f03f000000000000004000000000"
        "0000084000000000000000000000000000000000000000000000f03f0000000000002440000000000000000000000000"
        "000000000000000000000000182d4454fb21f93f00000000000000000000000000002440000000000000000000000000"
        "0000"
    )

    assert _LegacyGeometryEncoder(entities).encode() == expected
