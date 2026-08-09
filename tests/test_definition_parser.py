# SPDX-License-Identifier: MIT
"""Tests for modern component-definition parsing."""

from __future__ import annotations

import struct

from skppy.parser.definitions import parse_definitions

# Wire literals are independent from parser enums: 0x1771/0x157C delimit the
# definition list/record, 0x1388 its entities, and 0x1B58 its behavior block.


def _record(tag: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HI", tag, len(payload)) + payload


def _definition_entity_base(definition_id: int) -> bytes:
    # 0x07D0 entity base -> 0x05DC ID wrapper -> 0x05DE persistent ID.
    return _record(
        0x07D0,
        _record(
            0x05DC,
            _record(0x05DE, struct.pack("<H", definition_id)),
        ),
    )


def _vertex(vertex_id: int) -> bytes:
    return _record(
        0x09C4,
        _record(
            0x05DC,
            _record(0x05DE, struct.pack("<H", vertex_id)),
        )
        + _record(0x09C5, struct.pack("<3d", 1, 2, 3)),
    )


def test_parse_definition_preserves_identity_entities_and_behavior() -> None:
    """Decode a complete definition into the version-neutral public class."""
    definition_id = 300
    entities = _record(
        0x1388,
        _definition_entity_base(definition_id) + _record(0x1389, _vertex(301)),
    )
    behavior = _record(
        0x1B58,
        _record(0x1B59, b"\x02")
        + _record(0x1B5A, b"\x05")
        + _record(0x1B5B, b"\x01")
        + _record(0x1B5C, b"\x01")
        + _record(0x1B5D, b"\x00")
        + _record(0x1B5E, b"\x01"),
    )
    record = _record(
        0x157C,
        entities
        + _record(0x157D, bytes(range(16)))
        + _record(0x157E, b"Cabinet")
        + _record(0x157F, b"Base cabinet")
        + _record(0x1580, b"library.skp")
        + _record(0x1581, b"\x34\x12")
        + _record(0x1582, b"\x01")
        + _record(0x1583, b"\x03")
        + _record(0x1585, b"packed")
        + behavior,
    )
    payload = _record(
        0x1771,
        _record(0x7FFF, b"ignored") + record,
    )

    definition = parse_definitions(payload)[0]

    assert definition.id == definition_id
    assert definition.guid == bytes(range(16))
    assert definition.name == "Cabinet"
    assert definition.description == "Base cabinet"
    assert definition.loaded_from == "library.skp"
    assert definition.timestamp == 0x1234
    assert definition.modified is True
    assert definition.definition_type == 3
    assert definition.packed_payload == b"packed"
    assert definition.entities.vertices[0].id == 301
    assert definition.behavior_snap_mode == 2
    assert definition.behavior_no_scale_mask == 5
    assert definition.behavior_snap_enabled is True
    assert definition.behavior_cuts_opening is True
    assert definition.behavior_always_face_camera is False
    assert definition.behavior_shadows_face_sun is True


def test_parse_definition_uses_stable_defaults_for_sparse_record() -> None:
    """Construct a usable sparse definition without inventing file values."""
    entities = _record(0x1388, _definition_entity_base(9))
    payload = _record(
        0x1771,
        _record(0x157C, entities),
    )

    definition = parse_definitions(payload)[0]

    assert definition.id == 9
    assert definition.name == "definition_9"
    assert definition.guid == b"\x00" * 16
    assert definition.description == ""
    assert definition.packed_payload is None
    assert definition.entities.vertices == []


def test_parse_definitions_requires_list_container() -> None:
    """Return an empty collection for absent or unrelated list records."""
    assert parse_definitions(b"") == []
    assert parse_definitions(_record(0x7FFF, b"ignored")) == []
