# SPDX-License-Identifier: MIT
"""Tests for modern saved-scene parsing."""

from __future__ import annotations

import struct

from skppy.parser.scenes_parser import parse_scenes

# Scene fixtures use raw tags: 0x6D60/0x6D61 contain 0x7148 records; 0x6F54
# stores identity text, 0x7149-0x7156 store state, and 0x34BC stores a camera.


def _record(tag: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HI", tag, len(payload)) + payload


def _camera() -> bytes:
    payload = b"".join(
        (
            _record(0x34BD, struct.pack("<3d", 1, 2, 3)),
            _record(0x34BE, struct.pack("<3d", 4, 5, 6)),
            _record(0x34BF, struct.pack("<3d", 0, 0, 1)),
            _record(0x34C4, struct.pack("<d", 0.0)),
            _record(0x34C0, struct.pack("<d", 0.0)),
            _record(0x34C8, b"Scene camera"),
        )
    )
    return _record(0x34BC, payload)


def test_parse_scene_preserves_persistent_id_camera_and_references() -> None:
    """Decode repeated references and the camera stored by a named scene."""
    base = _record(
        0x6F54,
        _record(
            0x05DC,
            _record(0x05DE, b"\x34\x12"),
        )
        + _record(0x6F55, b"Details")
        + _record(0x6F56, b"Close view"),
    )
    scene = _record(
        0x7148,
        base
        + _record(0x7149, b"\x07")
        + _record(0x714B, b"\x01")
        + _record(0x714B, b"\x02\x01")
        + _record(0x7150, b"\x03")
        + _record(0x7150, b"\x04")
        + _record(0x7151, b"\x05")
        + _record(0x714C, b"\x06")
        + _record(0x7156, b"\x08")
        + _record(0x7152, b"\x00")
        + _record(0x714A, _camera()),
    )
    payload = _record(
        0x6D60,
        _record(0x6D61, scene),
    )

    parsed = parse_scenes(payload)[0]

    assert parsed.id == 0x1234
    assert parsed.name == "Details"
    assert parsed.description == "Close view"
    assert parsed.flags == 7
    assert parsed.hidden_entity_ids == [1, 258]
    assert parsed.hidden_layer_ids == [3, 4]
    assert parsed.active_section_plane_ids == [5]
    assert parsed.style_reference == 6
    assert parsed.background_image_ref == 8
    assert parsed.show_in_slideshow is False
    assert parsed.camera is not None
    assert parsed.camera.name == "Scene camera"
    assert parsed.camera.eye.to_tuple() == (1.0, 2.0, 3.0)
    assert parsed.camera.fov == 0.0
    assert parsed.camera.near == 0.0


def test_parse_scene_uses_fallback_id_and_name() -> None:
    """Use deterministic fallbacks only when persistent fields are absent."""
    records = _record(0x7148) + _record(0x7148)
    payload = _record(
        0x6D60,
        _record(0x6D61, records),
    )

    scenes = parse_scenes(payload)

    assert [(scene.id, scene.name) for scene in scenes] == [
        (1, "Scene 1"),
        (2, "Scene 2"),
    ]
    assert all(scene.camera is None for scene in scenes)


def test_parse_scenes_requires_container_and_list() -> None:
    """Return no scenes when either hierarchy level is absent."""
    assert parse_scenes(b"") == []
    assert parse_scenes(_record(0x7FFF, b"ignored")) == []
    assert parse_scenes(_record(0x6D60)) == []
