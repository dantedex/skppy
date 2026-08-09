# SPDX-License-Identifier: MIT
"""Raw SU2017 curve and arc-curve writer fixtures."""

import math

import numpy as np
import pytest

import skppy
from skppy.legacy_writter import build_legacy_2017_model
from skppy.legacy_writter.model import _LegacyGeometryEncoder


def test_arc_curve_matches_raw_sdk_object_payload() -> None:
    model = skppy.Model.new()
    model.entities.add_arc_curve((0, 0, 0), (0, 0, 1), 10, 0, math.pi / 2, 12)
    expected = bytes.fromhex(
        "ffff0300090043417263437572766500000115000c000000000000000000000000000000000000000000000000000000"
        "00000000000000000000000000000000000000000000f03f000000000000244000000000000000000000000000000000"
        "0000000000000000182d4454fb21f93f000000000000000000000000000024400000000000000000"
    )

    encoded = build_legacy_2017_model(model)

    assert expected in encoded


def test_writes_simple_polygon_curve_and_reuses_its_reference() -> None:
    model = skppy.Model.new()
    vertices = [model.entities.add_vertex(index, 0, 0) for index in range(3)]
    edges = [model.entities.add_edge(vertices[index], vertices[index + 1]) for index in range(2)]
    curve = skppy.Curve(id=model.entities._alloc_id(), edge_ids=[edge.id for edge in edges], is_polygon=True)
    model.entities.curves.append(curve)
    for edge in edges:
        edge.curve_id = curve.id
    expected_body = bytes.fromhex("ffff04000600434375727665000001150102000000")

    encoded = build_legacy_2017_model(model)

    assert expected_body in encoded


def test_writes_nested_arc_and_instance_transform_independently() -> None:
    model = skppy.Model.new()
    definition = model.add_definition("Arc")
    definition.entities.add_arc_curve((0, 0, 0), (0, 0, 1), 2, 0, math.pi / 2, 2)
    transform = skppy.Transform.from_translation(10, 20, 30).matrix
    transform[:3, :3] *= 3
    model.entities.add_instance(definition, skppy.Transform(transform))

    encoded = build_legacy_2017_model(model)

    assert np.array((10.0, 20.0, 30.0), dtype="<f8").tobytes() in encoded
    assert np.float64(2.0).tobytes() in encoded


def test_preserves_arc_under_nonuniform_instance_transform() -> None:
    model = skppy.Model.new()
    definition = model.add_definition("Arc")
    definition.entities.add_arc_curve((0, 0, 0), (0, 0, 1), 2, 0, math.pi / 2, 2)
    transform = np.eye(4)
    transform[0, 0] = 2
    model.entities.add_instance(definition, skppy.Transform(transform))

    encoded = build_legacy_2017_model(model)

    assert b"CArcCurve" in encoded
    assert np.float64(2.0).tobytes() in encoded


def test_rejects_invalid_curve_and_arc_references() -> None:
    missing_curve = skppy.Model.new()
    vertices = [missing_curve.entities.add_vertex(index, 0, 0) for index in range(2)]
    edge = missing_curve.entities.add_edge(*vertices)
    edge.curve_id = 99
    with pytest.raises(ValueError, match="missing curve ID 99"):
        build_legacy_2017_model(missing_curve)

    incomplete = skppy.Model.new()
    vertices = [incomplete.entities.add_vertex(index, 0, 0) for index in range(2)]
    edge = incomplete.entities.add_edge(*vertices)
    arc = skppy.ArcCurve(id=incomplete.entities._alloc_id(), edge_ids=[edge.id])
    incomplete.entities.arc_curves.append(arc)
    edge.curve_id = arc.id
    with pytest.raises(ValueError, match="incomplete geometric parameters"):
        build_legacy_2017_model(incomplete)


def test_encoder_rejects_malformed_arc_payloads() -> None:
    missing_curve = skppy.Entities()
    vertices = [missing_curve.add_vertex(index, 0, 0) for index in range(2)]
    missing_curve.add_edge(*vertices).curve_id = 99
    with pytest.raises(ValueError, match="missing curve ID 99"):
        _LegacyGeometryEncoder(missing_curve).encode()

    incomplete = skppy.Entities()
    vertices = [incomplete.add_vertex(index, 0, 0) for index in range(2)]
    edge = incomplete.add_edge(*vertices)
    arc = skppy.ArcCurve(id=incomplete._alloc_id(), edge_ids=[edge.id])
    incomplete.arc_curves.append(arc)
    edge.curve_id = arc.id
    with pytest.raises(ValueError, match="incomplete geometric parameters"):
        _LegacyGeometryEncoder(incomplete).encode()

    edge_less = skppy.Entities()
    vertices = [edge_less.add_vertex(index, 0, 0) for index in range(2)]
    edge = edge_less.add_edge(*vertices)
    arc = skppy.ArcCurve(
        id=edge_less._alloc_id(),
        edge_ids=[],
        center=(0, 0, 0),
        normal=(0, 0, 1),
        radius=1,
        start_angle=0,
        end_angle=math.pi,
    )
    edge_less.arc_curves.append(arc)
    edge.curve_id = arc.id
    with pytest.raises(ValueError, match="no resolvable first edge"):
        _LegacyGeometryEncoder(edge_less).encode()


def test_rejects_edge_less_and_degenerate_arcs_during_flattening() -> None:
    edge_less = skppy.Model.new()
    edge_less.entities.arc_curves.append(
        skppy.ArcCurve(
            id=edge_less.entities._alloc_id(),
            edge_ids=[],
            center=(0, 0, 0),
            normal=(0, 0, 1),
            radius=1,
            start_angle=0,
            end_angle=math.pi,
        )
    )
    with pytest.raises(ValueError, match="no resolvable first edge"):
        build_legacy_2017_model(edge_less)

    degenerate = skppy.Model.new()
    degenerate.entities.add_arc_curve((0, 0, 0), (0, 0, 1), 1, 0, math.pi, 2).normal = (0, 0, 0)
    with pytest.raises(ValueError, match="arc normal is degenerate"):
        build_legacy_2017_model(degenerate)
