# SPDX-License-Identifier: MIT
"""Tests for independent modern geometry serialization."""

from __future__ import annotations

import math
import struct
from collections.abc import Callable

import pytest

from skppy.data_structure.annotations import LinearDimension, RadialDimension, Text
from skppy.data_structure.construction import GuideLine, GuidePoint, SectionPlane
from skppy.data_structure.entities import (
    EDGE_FLAG_HIDDEN,
    EDGE_FLAG_SMOOTH,
    EDGE_FLAG_SOFT,
    ArcCurve,
    ComponentInstance,
    Curve,
    Edge,
    EdgeUse,
    Entities,
    Face,
    FaceUVProjection,
    Image,
    Loop,
    UVPin,
    Vertex,
)
from skppy.data_structure.model_metadata import AttributeDictionary
from skppy.data_structure.primitives import Vector2D, Vector3D
from skppy.writer.entities import encode_entities


def _raw_record(tag: int, payload: bytes = b"") -> bytes:
    """Construct expected wire bytes without relying on writer helpers."""
    return struct.pack("<HI", tag, len(payload)) + payload


def _scope_prefix() -> bytes:
    """Return the entities-level drawing-element state in raw wire form."""
    return _raw_record(0x07D0, _raw_record(0x07D3, b"\x06"))


def _scope_suffix() -> bytes:
    """Return the empty set, metadata pair, and component-state sentinel."""
    metadata = _raw_record(0x639F) + _raw_record(0x63A0)
    return _raw_record(0x139E) + _raw_record(0x139B, metadata) + _raw_record(0x139F, b"\x00")


def _triangle() -> Entities:
    entities = Entities()
    entities.vertices = [
        Vertex(1, Vector3D(0.0, 0.0, 0.0)),
        Vertex(2, Vector3D(1.0, 0.0, 0.0)),
        Vertex(3, Vector3D(0.0, 1.0, 0.0)),
    ]
    entities.edges = [
        Edge(4, 1, 2, EDGE_FLAG_HIDDEN | EDGE_FLAG_SOFT | EDGE_FLAG_SMOOTH),
        Edge(5, 2, 3),
        Edge(6, 3, 1),
    ]
    entities.faces = [
        Face(
            id=7,
            plane=(0.0, 0.0, 1.0, 0.0),
            outer_loop=Loop(
                [EdgeUse(4, False), EdgeUse(5, False), EdgeUse(6, False)],
                is_outer=True,
            ),
            inner_loops=[],
            front_material_id=8,
            back_material_id=9,
        )
    ]
    return entities


def test_empty_entities_has_three_explicit_core_sections() -> None:
    """Keep empty geometry sections present in their canonical order."""
    payload = b"".join(
        (
            _scope_prefix(),
            _raw_record(0x1389),  # Vertices section.
            _raw_record(0x138A),  # Edges section.
            _raw_record(0x138B),  # Faces section.
            _raw_record(0x138C),  # Component instances section.
            _raw_record(0x138D),  # Groups section.
            _scope_suffix(),
        )
    )
    assert encode_entities(Entities()) == _raw_record(0x1388, payload)


def test_vertex_layout_uses_nested_identity_and_float64_position() -> None:
    """Match the observed nested ID wrapper and vector representation."""
    identity = _raw_record(0x05DC, _raw_record(0x05DE, b"\x01"))
    position = _raw_record(0x09C5, struct.pack("<3d", 1.5, -2.0, 3.25))
    vertices = _raw_record(0x1389, _raw_record(0x09C4, identity + position))
    payload = (
        _scope_prefix()
        + vertices
        + _raw_record(0x138A)
        + _raw_record(0x138B)
        + _raw_record(0x138C)
        + _raw_record(0x138D)
        + _scope_suffix()
    )

    entities = Entities(vertices=[Vertex(1, Vector3D(1.5, -2.0, 3.25))])
    assert encode_entities(entities) == _raw_record(0x1388, payload)


def test_triangle_matches_raw_topology_and_flag_records() -> None:
    """Preserve IDs, topology, materials, planes, and modern wire flags."""
    encoded = encode_entities(_triangle())
    first_vertex = _raw_record(
        0x09C4,
        _raw_record(0x05DC, _raw_record(0x05DE, b"\x01")) + _raw_record(0x09C5, struct.pack("<3d", 0.0, 0.0, 0.0)),
    )
    first_edge = _raw_record(
        0x0BB8,
        _raw_record(
            0x07D0,
            _raw_record(0x05DC, _raw_record(0x05DE, b"\x04")) + _raw_record(0x07D3, b"\x1f"),
        )
        + _raw_record(0x0BB9, b"\x01")
        + _raw_record(0x0BBA, b"\x02"),
    )
    assert first_vertex in encoded
    assert first_edge in encoded
    assert _raw_record(0x0DAD, struct.pack("<4d", 0.0, 0.0, 1.0, 0.0)) in encoded
    assert _raw_record(0x0DAF, b"\x09") in encoded


def test_material_and_layer_references_use_distinct_wire_fields() -> None:
    """Write layer ownership in 0x07D2 and the back material in 0x0DAF."""
    entities = _triangle()
    entities.edges[0].layer_id = 10
    entities.faces[0].layer_id = 11

    encoded = encode_entities(
        entities,
        material_id_map={8: 31, 9: 32},
        layer_id_map={10: 21, 11: 22},
    )

    face_properties = _raw_record(0x07D1, b"\x1f") + _raw_record(0x07D2, b"\x16") + _raw_record(0x07D3, b"\x06")
    assert face_properties in encoded
    assert _raw_record(0x0DAF, b"\x20") in encoded

    assert _raw_record(0x07D2, b"\x15") in encoded


def test_construction_entities_match_raw_official_layout() -> None:
    """Encode infinite guides and section planes in their modern sections."""
    entities = Entities(
        guide_lines=[
            GuideLine(
                id=1,
                point=(1.0, 2.0, 3.0),
                direction=(0.0, 1.0, 0.0),
                stipple_pattern=0xFFFF,
                start_parameter=0.0,
                end_parameter=5.0,
                layer_id=10,
            )
        ],
        guide_points=[
            GuidePoint(
                id=2,
                position=(4.0, 5.0, 6.0),
                reference_point=(7.0, 8.0, 9.0),
                layer_id=10,
            )
        ],
        section_planes=[
            SectionPlane(
                id=3,
                plane=(1.0, 0.0, 0.0, -7.0),
                name="Section",
                symbol="S",
                layer_id=10,
            )
        ],
    )

    encoded = encode_entities(entities, layer_id_map={10: 20})

    assert (
        _raw_record(
            0x426A,
            struct.pack("<8d", 1.0, 2.0, 3.0, 0.0, 1.0, 0.0, 0.0, 5.0),
        )
        in encoded
    )
    assert _raw_record(0x426B, b"\xff\xff") in encoded
    assert _raw_record(0x426D, struct.pack("<3d", 4.0, 5.0, 6.0)) in encoded
    assert _raw_record(0x426E, struct.pack("<3d", 7.0, 8.0, 9.0)) in encoded
    assert _raw_record(0x426F, b"\x01") in encoded
    assert _raw_record(0x445D, struct.pack("<4d", 1.0, 0.0, 0.0, -7.0)) in encoded
    assert _raw_record(0x445E, b"Section") in encoded
    assert _raw_record(0x445F, b"S") in encoded


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda entities: setattr(entities.edges[0], "start_vertex_id", 99), "vertex"),
        (lambda entities: setattr(entities.faces[0], "id", 1), "unique"),
        (lambda entities: entities.images.append(Image(id=1)), "unique"),
        (lambda entities: entities.texts.append(Text(id=1)), "unique"),
        (
            lambda entities: entities.linear_dimensions.append(LinearDimension(id=1)),
            "unique",
        ),
        (
            lambda entities: entities.radial_dimensions.append(RadialDimension(id=1)),
            "unique",
        ),
        (
            lambda entities: setattr(entities.faces[0].outer_loop.edge_uses[0], "edge_id", 99),
            "missing edge",
        ),
        (
            lambda entities: setattr(entities.faces[0].outer_loop.edge_uses[1], "reversed", True),
            "disconnected loop",
        ),
    ],
)
def test_invalid_geometry_references_are_rejected(mutate: Callable[[Entities], None], message: str) -> None:
    """Reject graphs that would produce dangling modern entity references."""
    entities = _triangle()
    mutate(entities)
    with pytest.raises(ValueError, match=message):
        encode_entities(entities)


def test_invalid_entity_data_is_not_silently_discarded() -> None:
    """Report dangling image and curve references before encoding."""
    entities = _triangle()
    entities.images.append(Image(id=10))
    with pytest.raises(ValueError, match="Missing definition ID mapping"):
        encode_entities(entities)

    entities.images.clear()
    entities.edges[0].curve_id = 20
    with pytest.raises(ValueError, match="missing curve"):
        encode_entities(entities)


def test_arc_curve_encodes_official_geometry_payload_and_edge_ownership() -> None:
    """Write the 16-double modern Arc3d payload consumed by the SDK."""
    entities = Entities()
    arc = entities.add_arc_curve(
        center=(0.0, 0.0, 0.0),
        normal=(0.0, 0.0, 1.0),
        radius=10.0,
        start_angle=0.0,
        end_angle=math.pi / 2.0,
        segments=2,
    )

    encoded = encode_entities(entities)
    arc_geometry = struct.pack(
        "<16d",
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        -0.0,
        10.0,
        0.0,
        0.0,
        0.0,
        10.0,
        0.0,
        10.0,
        0.0,
        math.pi / 2.0,
    )
    curve = _raw_record(
        0x4A38,
        _raw_record(0x05DC, _raw_record(0x05DE, bytes((arc.id,))))
        + _raw_record(0x4A39, struct.pack("<I", 2))
        + _raw_record(0x4A3A, b"\x00")
        + _raw_record(0x4A3B, bytes((arc.edge_ids[0],)))
        + _raw_record(0x4A3C, bytes((arc.edge_ids[-1],))),
    )
    expected = _raw_record(
        0x1397,
        _raw_record(0x4C2C, curve + _raw_record(0x4C2D, arc_geometry)),
    )

    assert expected in encoded
    assert encoded.count(_raw_record(0x0BBB, bytes((arc.id,)))) == 2


def test_arc_curve_rejects_inconsistent_edge_ownership() -> None:
    entities = Entities()
    entities.add_arc_curve((0, 0, 0), (0, 0, 1), 2.0, 0.0, math.pi, 4)
    entities.edges[0].curve_id = None

    with pytest.raises(ValueError, match="owning curve"):
        encode_entities(entities)


def test_arc_curve_can_own_existing_face_edges() -> None:
    entities = Entities()
    face = entities.add_face([(2, 0, 0), (0, 2, 0), (-2, 0, 0), (0, -2, 0)])
    edge_ids = [use.edge_id for use in face.outer_loop.edge_uses]

    arc = entities.add_arc_curve_from_edges(edge_ids, (0, 0, 0), (0, 0, 1), 2.0, 0.0, 2 * math.pi)

    encoded = encode_entities(entities)
    expected_curve = _raw_record(
        0x4A38,
        _raw_record(0x05DC, _raw_record(0x05DE, bytes((arc.id,))))
        + _raw_record(0x4A39, struct.pack("<I", 4))
        + _raw_record(0x4A3A, b"\x00")
        + _raw_record(0x4A3B, bytes((edge_ids[0],)))
        + _raw_record(0x4A3C, bytes((edge_ids[-1],))),
    )

    assert expected_curve in encoded
    assert encoded.count(_raw_record(0x0BBB, bytes((arc.id,)))) == 4


def test_invalid_uv_projection_is_rejected() -> None:
    """Require complete finite affine projection data before writing a face."""
    entities = _triangle()
    entities.faces[0].front_uv = FaceUVProjection(transform=[1.0, 0.0])
    with pytest.raises(ValueError, match="9 finite"):
        encode_entities(entities)

    entities = _triangle()
    entities.faces[0].front_uv = FaceUVProjection(origin=(1.0, 2.0))
    with pytest.raises(ValueError, match="origin must contain 3 finite"):
        encode_entities(entities)

    entities = _triangle()
    entities.faces[0].front_uv = FaceUVProjection(pins=[UVPin(Vector2D(float("nan"), 0.0), Vector2D(0.0, 0.0))])
    with pytest.raises(ValueError, match="pins must contain finite"):
        encode_entities(entities)


def test_edge_flags_reject_unknown_bits() -> None:
    entities = _triangle()
    entities.edges[0].flags = 0x80
    with pytest.raises(ValueError, match="unsupported bits"):
        encode_entities(entities)


def test_uv_projection_matches_raw_transform_origin_and_pins() -> None:
    """Preserve the complete enabled face-side projection payload."""
    entities = _triangle()
    projection = FaceUVProjection(
        transform=[2.0, 0.0, 0.0, 0.0, 3.0, 0.0, 4.0, 5.0, 1.0],
        origin=(1.0, 2.0, 3.0),
        pins=[UVPin(Vector2D(0.25, 0.5), Vector2D(10.0, 20.0))],
    )
    entities.faces[0].front_uv = projection

    encoded = encode_entities(entities)
    pin = _raw_record(
        0x2718,
        _raw_record(0x2719, struct.pack("<2d", 0.25, 0.5)) + _raw_record(0x271A, struct.pack("<2d", 10.0, 20.0)),
    )
    assert _raw_record(0x2714, struct.pack("<I", 1)) in encoded
    assert _raw_record(0x2715, struct.pack("<9d", *projection.transform)) in encoded
    assert _raw_record(0x2716, struct.pack("<3d", *projection.origin)) in encoded
    assert _raw_record(0x2717, pin) in encoded


def test_polyline_curve_matches_raw_curve_section() -> None:
    entities = Entities(
        vertices=[
            Vertex(1, Vector3D(0.0, 0.0, 0.0)),
            Vertex(2, Vector3D(1.0, 0.0, 0.0)),
        ],
        edges=[Edge(3, 1, 2, curve_id=4)],
        curves=[Curve(id=4, edge_ids=[3], is_polygon=True)],
    )
    curve = _raw_record(
        0x4A38,
        _raw_record(0x05DC, _raw_record(0x05DE, b"\x04"))
        + _raw_record(0x4A39, struct.pack("<I", 1))
        + _raw_record(0x4A3A, b"\x01")
        + _raw_record(0x4A3B, b"\x03")
        + _raw_record(0x4A3C, b"\x03"),
    )

    assert _raw_record(0x1396, curve) in encode_entities(entities)


def test_raw_arc_payload_matches_literal_arc_specific_record() -> None:
    entities = Entities()
    arc = entities.add_arc_curve((0, 0, 0), (0, 0, 1), 2.0, 0.0, math.pi, segments=2)
    arc.center = None
    arc.normal = None
    arc.radius = None
    arc.start_angle = None
    arc.end_angle = None
    arc.raw_arc_payload = bytes(range(128))

    assert _raw_record(0x4C2D, bytes(range(128))) in encode_entities(entities)


def test_entity_id_maps_reject_incomplete_or_ambiguous_values() -> None:
    one = Entities(vertices=[Vertex(1, Vector3D(0.0, 0.0, 0.0))])
    with pytest.raises(ValueError, match="does not cover"):
        encode_entities(one, id_map={})
    with pytest.raises(ValueError, match="Mapped entity IDs must be positive"):
        encode_entities(one, id_map={1: 0})

    two = Entities(
        vertices=[
            Vertex(1, Vector3D(0.0, 0.0, 0.0)),
            Vertex(2, Vector3D(1.0, 0.0, 0.0)),
        ]
    )
    with pytest.raises(ValueError, match="Mapped entity IDs must be unique"):
        encode_entities(two, id_map={1: 18, 2: 18})


def test_scope_rejects_unsupported_and_unknown_attribute_owners() -> None:
    entities = Entities()
    entities.relationships.append(object())  # type: ignore[arg-type]
    with pytest.raises(NotImplementedError, match="relationships"):
        encode_entities(entities)

    entities = Entities()
    entities.attribute_dictionaries_by_entity_id[99] = [AttributeDictionary(name="Unknown")]
    with pytest.raises(ValueError, match="unknown entity IDs"):
        encode_entities(entities)


@pytest.mark.parametrize(
    ("instance", "message"),
    [
        (
            ComponentInstance(id=1, definition_id=1, transform=(1.0,)),
            "transform must contain 13 finite values",
        ),
        (
            ComponentInstance(id=1, definition_id=1, guid=b"short"),
            "GUID must contain 16 bytes",
        ),
        (
            ComponentInstance(id=1, definition_id=1, layer_id=0),
            "invalid layer reference",
        ),
    ],
)
def test_instances_reject_unrepresentable_data(instance: ComponentInstance, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        encode_entities(Entities(component_instances=[instance]), definition_id_map={1: 18})


def test_missing_layer_mapping_is_rejected() -> None:
    entities = Entities(
        vertices=[
            Vertex(1, Vector3D(0.0, 0.0, 0.0)),
            Vertex(2, Vector3D(1.0, 0.0, 0.0)),
        ],
        edges=[Edge(3, 1, 2, layer_id=7)],
    )
    with pytest.raises(ValueError, match="Missing layer ID mapping"):
        encode_entities(entities, layer_id_map={})


@pytest.mark.parametrize(
    ("entities", "message"),
    [
        (
            Entities(guide_points=[GuidePoint(id=1, position=(float("nan"), 0.0, 0.0))]),
            "non-finite position",
        ),
        (
            Entities(
                guide_points=[
                    GuidePoint(
                        id=1,
                        position=(0.0, 0.0, 0.0),
                        reference_point=(float("nan"), 0.0, 0.0),
                    )
                ]
            ),
            "non-finite reference",
        ),
        (
            Entities(guide_lines=[GuideLine(id=1, point=(float("nan"), 0.0, 0.0))]),
            "non-finite geometry",
        ),
        (
            Entities(guide_lines=[GuideLine(id=1, direction=(2.0, 0.0, 0.0))]),
            "must be a unit vector",
        ),
        (
            Entities(guide_lines=[GuideLine(id=1, stipple_pattern=0x10000)]),
            "stipple must fit in u16",
        ),
        (
            Entities(guide_lines=[GuideLine(id=1, start_parameter=1.0, end_parameter=1.0)]),
            "invalid parameter bounds",
        ),
        (
            Entities(section_planes=[SectionPlane(id=1, plane=(1.0, 0.0, 0.0))]),
            "invalid plane",
        ),
        (
            Entities(section_planes=[SectionPlane(id=1, plane=(0.0, 0.0, 0.0, 1.0))]),
            "zero normal",
        ),
    ],
)
def test_construction_entities_reject_invalid_geometry(entities: Entities, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        encode_entities(entities)


def test_geometry_rejects_non_positive_ids_and_non_finite_vertices() -> None:
    with pytest.raises(ValueError, match="IDs must be positive"):
        encode_entities(Entities(vertices=[Vertex(0, Vector3D(0.0, 0.0, 0.0))]))
    with pytest.raises(ValueError, match="non-finite position"):
        encode_entities(Entities(vertices=[Vertex(1, Vector3D(float("nan"), 0.0, 0.0))]))


def test_edges_and_curves_reject_invalid_topology() -> None:
    vertices = [
        Vertex(1, Vector3D(0.0, 0.0, 0.0)),
        Vertex(2, Vector3D(1.0, 0.0, 0.0)),
    ]
    with pytest.raises(ValueError, match="identical endpoints"):
        encode_entities(Entities(vertices=vertices, edges=[Edge(3, 1, 1)]))

    cases = (
        (Curve(id=4), [Edge(3, 1, 2)], "at least one edge"),
        (Curve(id=4, edge_ids=[3, 3]), [Edge(3, 1, 2, curve_id=4)], "duplicate"),
        (Curve(id=4, edge_ids=[99]), [Edge(3, 1, 2)], "missing edge"),
    )
    for curve, edges, message in cases:
        with pytest.raises(ValueError, match=message):
            encode_entities(Entities(vertices=vertices, edges=edges, curves=[curve]))


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda arc: (
                setattr(arc, "center", None),
                setattr(arc, "normal", None),
                setattr(arc, "radius", None),
                setattr(arc, "start_angle", None),
                setattr(arc, "end_angle", None),
            ),
            "needs a 128-byte raw payload",
        ),
        (lambda arc: setattr(arc, "center", None), "incomplete geometry"),
        (lambda arc: setattr(arc, "radius", float("nan")), "non-finite geometry"),
        (lambda arc: setattr(arc, "normal", (0.0, 0.0, 2.0)), "unit vector"),
        (lambda arc: setattr(arc, "radius", 0.0), "invalid radius or angles"),
    ],
)
def test_arc_curves_reject_unrepresentable_geometry(mutate: Callable[[ArcCurve], object], message: str) -> None:
    entities = Entities()
    arc = entities.add_arc_curve((0, 0, 0), (0, 0, 1), 2.0, 0.0, math.pi, segments=2)
    mutate(arc)
    with pytest.raises(ValueError, match=message):
        encode_entities(entities)


def test_faces_reject_invalid_plane_material_and_loop_size() -> None:
    entities = _triangle()
    entities.faces[0].plane = (1.0, 0.0, 0.0)
    with pytest.raises(ValueError, match="invalid plane"):
        encode_entities(entities)

    entities = _triangle()
    entities.faces[0].front_material_id = 0
    with pytest.raises(ValueError, match="invalid material reference"):
        encode_entities(entities)

    entities = _triangle()
    entities.faces[0].outer_loop.edge_uses = entities.faces[0].outer_loop.edge_uses[:2]
    with pytest.raises(ValueError, match="fewer than 3 edges"):
        encode_entities(entities)
