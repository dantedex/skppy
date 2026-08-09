# SPDX-License-Identifier: MIT
"""Raw-wire tests for modern linear dimension serialization."""

from __future__ import annotations

import struct

from skppy import LinearDimension, PointReference, Vector3D
from skppy.data_structure.entities import Entities
from skppy.writer.entities import encode_entities


def _record(tag: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HI", tag, len(payload)) + payload


def _point_reference(
    point: tuple[float, float, float],
    *,
    kind: int = 1,
    entity_id: int | None = None,
    instance_path_ids: tuple[int, ...] = (),
) -> bytes:
    style_payload = b""
    if entity_id is not None:
        style_payload += _record(0x53FD, bytes((entity_id,)))
    style_payload += _record(
        0x53FE,
        b"".join(bytes((1, path_id)) for path_id in instance_path_ids),
    )
    style = _record(0x53FC, style_payload)
    empty_style = _record(0x53FC, _record(0x53FE))
    value = b"".join(
        (
            _record(0x5209, struct.pack("<I", kind)),
            _record(0x520A, struct.pack("<3d", *point)),
            _record(0x520B, style),
            _record(0x520C, empty_style),
        )
    )
    return _record(0x5208, value)


def test_linear_dimension_matches_observed_raw_layout() -> None:
    dimension = LinearDimension(
        id=1,
        text="Writer length",
        font_id=3,
        arrow_type=3,
        start=PointReference(
            kind=5,
            position=Vector3D(0.25, 0.0, 0.0),
            entity_id=1,
            instance_path_ids=[1],
        ),
        end=PointReference(position=Vector3D(5.0, 2.0, 3.0)),
        direction=Vector3D(0.0, 0.0, 1.0),
        render_direction=Vector3D(1.0, 0.0, 0.0),
        mode=0,
        offset=0.0,
        line_position=0.0,
        alignment=1,
    )

    entity_base = _record(
        0x07D0,
        _record(0x05DC, _record(0x05DE, b"\x12")) + _record(0x07D3, b"\x06"),
    )
    common = _record(
        0x59D8,
        entity_base
        + _record(0x59D9, b"Writer length")
        + _record(0x59DA, b"\x03")
        + _record(0x59DB, b"\x00")
        + _record(0x59DC, struct.pack("<I", 3)),
    )
    dimension_payload = b"".join(
        (
            common,
            _record(
                0x5BCD,
                _point_reference(
                    (0.25, 0.0, 0.0),
                    kind=5,
                    entity_id=0x12,
                    instance_path_ids=(0x12,),
                ),
            ),
            _record(0x5BCE, _point_reference((5.0, 2.0, 3.0))),
            _record(0x5BCF, struct.pack("<3d", 0.0, 0.0, 1.0)),
            _record(0x5BD0, struct.pack("<3d", 1.0, 0.0, 0.0)),
            _record(0x5BD1, struct.pack("<I", 0)),
            _record(0x5BD3, struct.pack("<d", 0.0)),
            _record(0x5BD2, struct.pack("<d", 0.0)),
            _record(0x5BD4, struct.pack("<I", 1)),
        )
    )
    metadata = _record(0x639F) + _record(0x63A0)
    entities_payload = b"".join(
        (
            _record(0x07D0, _record(0x07D3, b"\x06")),
            _record(0x1389),
            _record(0x138A),
            _record(0x138B),
            _record(0x138C),
            _record(0x138D),
            _record(0x1399, _record(0x5BCC, dimension_payload)),
            _record(0x139E),
            _record(0x138E, b"\x01\x12"),
            _record(0x139B, metadata),
            _record(0x139F, b"\x00"),
        )
    )

    assert encode_entities(Entities(linear_dimensions=[dimension]), id_map={1: 18}) == _record(0x1388, entities_payload)
