# SPDX-License-Identifier: MIT
"""Raw-byte checks for modern placed-image serialization."""

from __future__ import annotations

import struct

from skppy.data_structure.entities import Entities, Image
from skppy.writer.entities import encode_entities


def _raw_record(tag: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HI", tag, len(payload)) + payload


def test_image_wraps_an_instance_record_in_raw_image_section() -> None:
    entities = Entities(
        images=[
            Image(
                id=1,
                guid=bytes(range(16)),
                name="Placed image",
                definition_id=10,
            )
        ]
    )
    encoded = encode_entities(
        entities,
        id_map={1: 18},
        definition_id_map={10: 19},
    )

    identity = _raw_record(0x05DC, _raw_record(0x05DE, b"\x12"))
    entity_base = _raw_record(
        0x07D0,
        identity + _raw_record(0x07D3, b"\x06"),
    )
    instance = b"".join(
        (
            entity_base,
            _raw_record(0x1965, b"Placed image"),
            _raw_record(
                0x1966,
                struct.pack(
                    "<13d",
                    1,
                    0,
                    0,
                    0,
                    1,
                    0,
                    0,
                    0,
                    1,
                    0,
                    0,
                    0,
                    1,
                ),
            ),
            _raw_record(0x1967, b"\x13"),
            _raw_record(0x1968, bytes(range(16))),
        )
    )
    expected = _raw_record(
        0x1390,
        _raw_record(0x1F40, _raw_record(0x1964, instance)),
    )

    assert expected in encoded

    default_ids = encode_entities(
        entities,
        definition_id_map={10: 19},
    )
    assert _raw_record(0x05DC, _raw_record(0x05DE, b"\x01")) in default_ids
