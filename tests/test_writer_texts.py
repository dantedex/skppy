# SPDX-License-Identifier: MIT
"""Raw-wire tests for modern text annotation serialization."""

from __future__ import annotations

import struct

import pytest

from skppy import PointReference, Text, Vector2D, Vector3D
from skppy.data_structure.entities import Entities
from skppy.data_structure.model_metadata import Font
from skppy.writer.entities import encode_entities


def _record(tag: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HI", tag, len(payload)) + payload


def test_text_matches_observed_raw_layout() -> None:
    text = Text(
        id=1,
        text="Writer text",
        anchor=PointReference(kind=1, position=Vector3D(1.0, 2.0, 3.0)),
        font_id=2,
        screen_position=Vector2D(0.25, 0.75),
        leader_vector=Vector3D(0.0, 0.0, 1.0),
        view_direction=Vector3D(0.0, 0.0, 1.0),
        leader_type=1,
        line_weight=1,
        arrow_type=3,
    )
    text.drawing.casts_shadows = False
    style = _record(0x53FC, _record(0x53FE))
    point_reference = _record(
        0x5208,
        _record(0x5209, struct.pack("<I", 1))
        + _record(0x520A, struct.pack("<3d", 1.0, 2.0, 3.0))
        + _record(0x520B, style)
        + _record(0x520C, style),
    )
    entity_base = _record(
        0x07D0,
        _record(0x05DC, _record(0x05DE, b"\x12")) + _record(0x07D3, b"\x04"),
    )
    text_payload = b"".join(
        (
            entity_base,
            _record(0x55F1, b"Writer text"),
            _record(0x55F2, struct.pack("<d", 0.25)),
            _record(0x55F3, struct.pack("<d", 0.75)),
            _record(0x55F4, point_reference),
            _record(0x55F5, struct.pack("<3d", 0.0, 0.0, 1.0)),
            _record(0x55F6, b"\x00"),
            _record(0x55F7, struct.pack("<3d", 0.0, 0.0, 1.0)),
            _record(0x55F8, b"\x00"),
            _record(0x55F9, b"\x02"),
            _record(0x55FA, struct.pack("<I", 1)),
            _record(0x55FB, struct.pack("<I", 1)),
            _record(0x55FC, b"\x01"),
            _record(0x55FD, struct.pack("<I", 3)),
            _record(0x55FE, struct.pack("<I", 0)),
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
            _record(0x1398, _record(0x55F0, text_payload)),
            _record(0x139E),
            _record(0x138E, b"\x01\x12"),
            _record(0x139B, metadata),
            _record(0x139F, b"\x00"),
        )
    )

    assert encode_entities(Entities(texts=[text]), id_map={1: 18}) == _record(0x1388, entities_payload)


def test_text_without_explicit_font_uses_required_default_font_bytes() -> None:
    """Keep font-less public annotations acceptable to the official reader."""
    encoded = encode_entities(Entities(texts=[Text(id=1)]), id_map={1: 18})

    assert _record(0x55F9, b"\x02") in encoded


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"screen_position": Vector2D(float("nan"), 0.0)}, "finite values"),
        ({"line_weight": -1}, "must fit in u32"),
        (
            {"convert_to_screen_on_explode": True},
            "do not expose convert-to-screen",
        ),
    ],
)
def test_text_rejects_unrepresentable_placement_and_flags(changes: dict, message: str) -> None:
    text = Text(id=1)
    for field, value in changes.items():
        setattr(text, field, value)
    with pytest.raises((ValueError, NotImplementedError), match=message):
        encode_entities(Entities(texts=[text]))


def test_annotation_font_objects_require_consistent_model_mapping() -> None:
    font = Font("Arial", point_size=12, world_size=1.0)
    text = Text(id=1, font=font)
    with pytest.raises(ValueError, match="require a model font mapping"):
        encode_entities(Entities(texts=[text]))
    with pytest.raises(ValueError, match="not registered"):
        encode_entities(Entities(texts=[text]), font_id_map={})

    text.font_id = 2
    with pytest.raises(ValueError, match="identify different fonts"):
        encode_entities(Entities(texts=[text]), font_id_map={id(font): 3})

    text.font = None
    text.font_id = 0
    with pytest.raises(ValueError, match="positive u32"):
        encode_entities(Entities(texts=[text]))


def test_point_references_reject_invalid_kinds_paths_and_entity_ids() -> None:
    invalid_kind = Text(id=1, anchor=PointReference(kind=-1))
    with pytest.raises(ValueError, match="kind must fit in u32"):
        encode_entities(Entities(texts=[invalid_kind]))

    path_without_entity = Text(id=1, anchor=PointReference(instance_path_ids=[1]))
    with pytest.raises(ValueError, match="paths require an associated entity"):
        encode_entities(Entities(texts=[path_without_entity]))

    unknown_entity = Text(id=1, anchor=PointReference(entity_id=99))
    with pytest.raises(ValueError, match="unknown entity ID"):
        encode_entities(Entities(texts=[unknown_entity]))


def test_annotation_rejects_unsupported_drawing_state() -> None:
    text = Text(id=1)
    text.drawing.soft = True
    with pytest.raises(NotImplementedError, match="soft, smooth, or locked"):
        encode_entities(Entities(texts=[text]))
