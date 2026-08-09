# SPDX-License-Identifier: MIT
"""Raw-wire tests for modern radial dimension serialization."""

from __future__ import annotations

import math
import struct

import pytest

from skppy import ArcGeometry, RadialDimension
from skppy.data_structure.entities import Entities
from skppy.writer.entities import encode_entities


def _record(tag: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HI", tag, len(payload)) + payload


def test_associated_radial_dimension_matches_observed_raw_layout() -> None:
    dimension = RadialDimension(
        id=1,
        text="Writer radius",
        font_id=2,
        arrow_type=3,
        target_entity_id=2,
        parameter=math.pi / 4.0,
        radius_ratio=1.5,
        is_diameter=True,
    )
    entity_base = _record(
        0x07D0,
        _record(0x05DC, _record(0x05DE, b"\x2e")) + _record(0x07D3, b"\x06"),
    )
    common = _record(
        0x59D8,
        entity_base
        + _record(0x59D9, b"Writer radius")
        + _record(0x59DA, b"\x02")
        + _record(0x59DB, b"\x00")
        + _record(0x59DC, struct.pack("<I", 3)),
    )
    radial_payload = b"".join(
        (
            common,
            _record(0x5DC1, b"\x13"),
            _record(0x5DC3, struct.pack("<d", math.pi / 4.0)),
            _record(0x5DC4, struct.pack("<d", 1.5)),
            _record(0x5DC5, b"\x01"),
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
            _record(0x139A, _record(0x5DC0, radial_payload)),
            _record(0x139E),
            _record(0x138E, b"\x01\x2e"),
            _record(0x139B, metadata),
            _record(0x139F, b"\x00"),
        )
    )

    assert encode_entities(Entities(radial_dimensions=[dimension]), id_map={1: 46, 2: 19}) == _record(
        0x1388, entities_payload
    )


def test_radial_dimensions_require_exactly_one_association_form() -> None:
    with pytest.raises(NotImplementedError, match="require an associated arc"):
        encode_entities(Entities(radial_dimensions=[RadialDimension(id=1)]))

    dimension = RadialDimension(id=1, target_entity_id=2, arc=ArcGeometry())
    with pytest.raises(ValueError, match="cannot also contain an inline arc"):
        encode_entities(Entities(radial_dimensions=[dimension]), id_map={1: 18, 2: 19})
