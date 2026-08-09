# SPDX-License-Identifier: MIT
"""Tests for modern layer and layer-folder parsing."""

from __future__ import annotations

import struct

import pytest

from skppy.parser.layers import parse_layers

# Raw tags keep fixtures independent: 0x3A99 is the layer list, 0x3C8C-0x3C90
# are layer fields, and 0x3A9B/0x3E80-0x3E84 encode the folder tree.


def _record(tag: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HI", tag, len(payload)) + payload


def _layer(layer_id: int, name: str, *fields: bytes) -> bytes:
    return _record(
        0x3C8C,
        _record(
            0x05DC,
            _record(0x05DE, struct.pack("<H", layer_id)),
        )
        + _record(0x3C8D, name.encode())
        + b"".join(fields),
    )


def test_parse_layers_preserves_explicit_state_and_defaults() -> None:
    """Decode layer state while retaining defaults for absent optional tags."""
    payload = _record(
        0x3A99,
        _layer(
            10,
            "Hidden",
            # 0x3C8E is a hidden bit: one means the layer is not visible.
            _record(0x3C8E, b"\x01"),
            _record(0x3C8F, b"\x07"),
            _record(0x3C90, b"\x05"),
        )
        + _record(0x7FFF, b"ignored")
        + _layer(11, "Default"),
    )

    layers, folders = parse_layers(payload)

    assert folders == []
    assert [(layer.id, layer.name) for layer in layers] == [
        (10, "Hidden"),
        (11, "Default"),
    ]
    assert layers[0].visible is False
    assert layers[0].material_id == 7
    assert layers[0].page_behavior == 5
    assert layers[1].visible is True
    assert layers[1].material_id is None
    assert layers[1].page_behavior == 0


def test_parse_layer_folders_recursively_preserves_membership() -> None:
    """Build nested folder hierarchy and layer membership in source order."""
    child = _record(
        0x3E80,
        _record(0x3E81, b"Child")
        # Folder visibility also uses an on-disk hidden bit.
        + _record(0x3E82, b"\x01")
        # 0x3E84 is not nested TLV: each ID has a one-byte width prefix.
        + _record(0x3E84, b"\x01\x0b"),
    )
    parent = _record(
        0x3E80,
        _record(0x3E81, b"Parent")
        + _record(
            0x3E84,
            b"\x01\x0a\x01\x0c",
        )
        + _record(0x3E83, child),
    )
    structural_root = _record(
        0x3E80,
        _record(0x3E81, b"") + _record(0x3E83, parent) + _record(0x3E84, b"") + _record(0x3E82, b"\x00"),
    )
    payload = _record(0x3A9B, structural_root)

    layers, folders = parse_layers(payload)

    assert layers == []
    assert folders[0].name == "Parent"
    assert folders[0].visible is True
    assert folders[0].child_layer_ids == [10, 12]
    assert folders[0].child_folders[0].name == "Child"
    assert folders[0].child_folders[0].visible is False
    assert folders[0].child_folders[0].child_layer_ids == [11]


def test_parse_layer_folder_rejects_truncated_member_id() -> None:
    """Reject a width prefix whose ID bytes are missing."""
    payload = _record(
        0x3A9B,
        _record(0x3E80, _record(0x3E84, b"\x02\x01")),
    )

    with pytest.raises(ValueError, match="Truncated layer folder ID sequence"):
        parse_layers(payload)


def test_parse_layers_accepts_empty_container() -> None:
    """Treat an empty modern layer container as an empty public collection."""
    assert parse_layers(b"") == ([], [])


def test_parse_layers_promotes_nested_display_material() -> None:
    """Decode the complete material record embedded in a modern layer."""
    # 0x32C8 is a material record; its 0x05DC wrapper contains object ID 42,
    # while 0x32CC names it and 0x32CA marks its embedded layer context.
    material = _record(
        0x32C8,
        _record(0x05DC, _record(0x05DE, struct.pack("<H", 42)))
        + _record(0x32CC, b"Layer_Display")
        + _record(0x32CA, b"\x01"),
    )
    payload = _record(
        0x3A99,
        _layer(10, "Display", _record(0x3C8F, material)),
    )

    layers, folders = parse_layers(payload)

    assert folders == []
    assert layers[0].material_id == 42
    assert layers[0].material is not None
    assert layers[0].material.id == 42
    assert layers[0].material.name == "Layer_Display"
    assert layers[0].material.alpha == 1.0
