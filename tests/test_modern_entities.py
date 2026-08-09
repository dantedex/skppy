# SPDX-License-Identifier: MIT
"""Integration tests for modern entity-section parsing."""

from __future__ import annotations

import struct

from skppy.parser.entities import parse_entities

# Public normalized edge bits are fixture expectations, not imported parser
# values: hidden=0x01, soft=0x02, smooth=0x04.
EDGE_FLAG_HIDDEN = 0x01
EDGE_FLAG_SOFT = 0x02
EDGE_FLAG_SMOOTH = 0x04

# Entity collection tags are 0x1389-0x1397. Their records use independent raw
# tags for vertices (0x09C4), edges (0x0BB8), faces (0x0DAC), instances
# (0x1964), curves (0x4A38), and construction geometry (0x4268-0x445F).


def _record(tag: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HI", tag, len(payload)) + payload


def _entity_base(
    entity_id: int,
    *,
    material_id: int | None = None,
    layer_id: int | None = None,
    flags: int = 0,
) -> bytes:
    # 0x07D0 entity base contains its 0x05DC/0x05DE ID and drawing properties.
    fields = _record(
        0x05DC,
        _record(0x05DE, struct.pack("<H", entity_id)),
    )
    if material_id is not None:
        fields += _record(0x07D1, bytes((material_id,)))
    if layer_id is not None:
        fields += _record(0x07D2, bytes((layer_id,)))
    fields += _record(0x07D3, bytes((flags,)))
    return _record(0x07D0, fields)


def _vertex(vertex_id: int, position: tuple[float, float, float]) -> bytes:
    return _record(
        0x09C4,
        _record(
            0x05DC,
            _record(0x05DE, struct.pack("<H", vertex_id)),
        )
        + _record(0x09C5, struct.pack("<3d", *position)),
    )


def _edge(
    edge_id: int,
    start: int,
    end: int,
    flags: int = 0,
    layer_id: int | None = None,
) -> bytes:
    return _record(
        0x0BB8,
        _entity_base(edge_id, flags=flags, layer_id=layer_id)
        + _record(0x0BB9, bytes((start,)))
        + _record(0x0BBA, bytes((end,)))
        + _record(0x0BBB, b"\x32"),
    )


def _edge_use(edge_id: int, reversed_: bool = False) -> bytes:
    return _record(
        0x0FA0,
        _record(0x0FA1, bytes((edge_id,))) + _record(0x0FA2, bytes((reversed_,))),
    )


def _instance_record(instance_id: int, name: str, layer_id: int = 8) -> bytes:
    transform = (1, 0, 0, 0, 1, 0, 0, 0, 1, 10, 20, 30, 1)
    return _record(
        0x1964,
        _entity_base(instance_id, material_id=7, layer_id=layer_id)
        + _record(0x1965, name.encode())
        + _record(0x1966, struct.pack("<13d", *transform))
        + _record(0x1967, b"\x63")
        + _record(0x1968, bytes(range(16))),
    )


def _curve_record(curve_id: int, first_edge: int, count: int) -> bytes:
    return _record(
        0x4A38,
        _record(
            0x05DC,
            _record(0x05DE, bytes((curve_id,))),
        )
        + _record(0x4A39, bytes((count,)))
        + _record(0x4A3B, bytes((first_edge,)))
        + _record(0x4A3A, b"\x01"),
    )


def test_curve_membership_uses_raw_edge_curve_references() -> None:
    """Do not infer a contiguous edge range from persistent IDs."""
    payload = _record(
        0x138A,
        _edge(10, 1, 2) + _edge(12, 2, 3) + _edge(15, 3, 4),
    ) + _record(0x1396, _curve_record(50, 10, 3))

    entities = parse_entities(payload)

    assert entities.curves[0].edge_ids == [10, 12, 15]


def test_parse_entities_decodes_complete_modern_scope() -> None:
    """Normalize all implemented modern entity families in one scope."""
    vertices = b"".join(
        (
            _vertex(1, (0, 0, 0)),
            _vertex(2, (1, 0, 0)),
            _vertex(3, (0, 1, 0)),
        )
    )
    edges = b"".join(
        (
            _edge(10, 1, 2, 0x01, layer_id=9),
            _edge(11, 2, 3, 0x08),
            _edge(12, 3, 1, 0x10),
        )
    )
    outer = _record(
        0x1194,
        _record(
            0x1195,
            _edge_use(10) + _edge_use(11, True) + _edge_use(12),
        ),
    )
    inner = _record(0x1194)
    face = _record(
        0x0DAC,
        _entity_base(20, material_id=4, layer_id=6)
        + _record(0x0DAF, b"\x05")
        + _record(0x0DAD, struct.pack("<4d", 0, 0, 1, -2))
        + _record(0x0DAE, outer + inner),
    )

    group = _record(0x1D4C, _instance_record(31, "Group"))
    image = _record(0x1F40, _instance_record(32, "Image"))
    arc = _record(
        0x4C2C,
        _curve_record(51, 10, 3) + _record(0x4C2D, b"arc geometry"),
    )
    guide_point = _record(
        0x426C,
        _record(0x4268, _entity_base(60, layer_id=13)) + _record(0x426D, struct.pack("<3d", 2, 3, 4)),
    )
    guide_line = _record(
        0x4269,
        _record(0x4268, _entity_base(61, layer_id=14))
        + _record(0x426A, struct.pack("<6d", 1, 2, 3, 0, 1, 0))
        + _record(0x426B, b"\xaa\xaa"),
    )
    section_plane = _record(
        0x445C,
        _entity_base(62, layer_id=15)
        + _record(0x445D, struct.pack("<4d", 1, 0, 0, -4))
        + _record(0x445E, b"Section A")
        + _record(0x445F, b"A"),
    )

    payload = b"".join(
        (
            _record(0x1389, vertices),
            _record(0x138A, edges),
            _record(0x138B, face),
            _record(0x138C, _instance_record(30, "Instance")),
            _record(0x138D, group),
            _record(0x1390, image),
            _record(0x1396, _curve_record(50, 10, 3)),
            _record(0x1397, arc),
            _record(0x1392, guide_point),
            _record(0x1391, guide_line),
            _record(0x1393, section_plane),
        )
    )

    entities = parse_entities(payload)

    assert [vertex.id for vertex in entities.vertices] == [1, 2, 3]
    assert [edge.flags for edge in entities.edges] == [
        EDGE_FLAG_HIDDEN,
        EDGE_FLAG_SOFT,
        EDGE_FLAG_SMOOTH,
    ]
    assert all(edge.curve_id == 50 for edge in entities.edges)
    assert entities.edges[0].layer_id == 9

    parsed_face = entities.faces[0]
    assert parsed_face.id == 20
    assert parsed_face.plane == (0.0, 0.0, 1.0, -2.0)
    assert parsed_face.front_material_id == 4
    assert parsed_face.back_material_id == 5
    assert parsed_face.layer_id == 6
    assert parsed_face.outer_loop.is_outer is True
    assert [use.edge_id for use in parsed_face.outer_loop.edge_uses] == [10, 11, 12]
    assert parsed_face.outer_loop.edge_uses[1].reversed is True
    assert len(parsed_face.inner_loops) == 1

    instance = entities.component_instances[0]
    assert (instance.id, instance.name, instance.definition_id) == (30, "Instance", 99)
    assert instance.material_id == 7
    assert instance.layer_id == 8
    assert instance.guid == bytes(range(16))
    assert instance.transform[9:12] == [10.0, 20.0, 30.0]
    assert (entities.groups[0].id, entities.groups[0].name) == (31, "Group")
    assert entities.groups[0].layer_id == 8
    assert (entities.images[0].id, entities.images[0].name) == (32, "Image")
    assert entities.images[0].layer_id == 8

    assert entities.curves[0].id == 50
    assert entities.curves[0].edge_ids == [10, 11, 12]
    assert entities.curves[0].is_polygon is True
    assert entities.arc_curves[0].id == 51
    assert entities.arc_curves[0].edge_ids == [10, 11, 12]
    assert entities.arc_curves[0].raw_arc_payload == b"arc geometry"
    assert entities.guide_points[0].position == (2.0, 3.0, 4.0)
    assert entities.guide_points[0].layer_id == 13
    assert entities.guide_lines[0].direction == (0.0, 1.0, 0.0)
    assert entities.guide_lines[0].stipple_pattern == 0xAAAA
    assert entities.guide_lines[0].layer_id == 14
    assert entities.section_planes[0].name == "Section A"
    assert entities.section_planes[0].plane == (1.0, 0.0, 0.0, -4.0)
    assert entities.section_planes[0].layer_id == 15


def test_parse_entities_handles_sparse_and_incomplete_records() -> None:
    """Skip unusable records while preserving valid sparse entity defaults."""
    sparse_face = _record(0x0DAC)
    sparse_edge = _record(0x0BB8)
    range_curve = _record(
        0x4A38,
        _record(0x05DC, _record(0x05DE, b"\x46")) + _record(0x4A3B, b"\x0a") + _record(0x4A3C, b"\x0c"),
    )
    payload = b"".join(
        (
            _record(
                0x1389,
                _record(0x09C4, _record(0x05DC)),
            ),
            _record(0x138A, sparse_edge),
            _record(0x138B, sparse_face),
            _record(0x138D, _record(0x1D4C)),
            _record(0x1390, _record(0x1F40)),
            _record(
                0x1396,
                _record(0x4A38) + range_curve,
            ),
            _record(
                0x1397,
                _record(0x4C2C),
            ),
        )
    )

    entities = parse_entities(payload)

    assert entities.vertices == []
    assert entities.edges[0].id == 0
    assert (entities.edges[0].start_vertex_id, entities.edges[0].end_vertex_id) == (
        0,
        0,
    )
    assert entities.faces[0].plane == (0.0, 0.0, 1.0, 0.0)
    assert entities.faces[0].outer_loop.edge_uses == []
    assert entities.groups == []
    assert entities.images == []
    assert entities.curves[0].edge_ids == [10, 11, 12]
    assert entities.arc_curves == []
