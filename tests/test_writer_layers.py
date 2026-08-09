# SPDX-License-Identifier: MIT
"""Tests for modern layer and folder serialization."""

from __future__ import annotations

import struct

import pytest

from skppy import Color, new_model
from skppy.data_structure.layers import Layer, LayerFolder
from skppy.data_structure.materials import Material
from skppy.writer.layers import _encode_folder, encode_layers
from skppy.writer.model_data import encode_model_data


def _raw_record(tag: int, payload: bytes = b"") -> bytes:
    """Construct expected wire bytes without writer helpers."""
    return struct.pack("<HI", tag, len(payload)) + payload


def test_layers_and_nested_folders_match_raw_global_ids() -> None:
    """Preserve layer state, display materials, active tag, and folder links."""
    model = new_model()
    walls = model.add_layer("Walls", visible=True)
    roof = model.add_layer("Roof", visible=False)
    walls.material = Material(
        id=100,
        name="Layer_Walls",
        color=Color(10, 20, 30),
    )
    model.active_layer_id = roof.id
    model.layer_folders = [
        LayerFolder(
            name="Building",
            child_layer_ids=[walls.id],
            child_folders=[LayerFolder(name="Upper", child_layer_ids=[roof.id])],
        )
    ]
    encoded = encode_model_data(model)

    assert _raw_record(0x3C8D, b"Walls") in encoded
    assert _raw_record(0x3C8D, b"Roof") in encoded
    assert _raw_record(0x3C8E, b"\x00") in encoded
    assert _raw_record(0x3C8E, b"\x01") in encoded
    assert _raw_record(0x3A9A, b"\x13") in encoded
    assert _raw_record(0x32CC, b"Layer_Walls") in encoded
    assert _raw_record(0x3E81, b"Building") in encoded
    assert _raw_record(0x3E84, b"\x01\x12") in encoded
    assert _raw_record(0x3E81, b"Upper") in encoded
    assert _raw_record(0x3E84, b"\x01\x13") in encoded


def test_layer_writer_rejects_unknown_active_and_folder_references() -> None:
    """Fail before serializing dangling layer references."""
    layer = Layer(id=1, name="Walls")
    kwargs = {
        "layer_id_map": {1: 18},
        "display_material_id_map": {1: 19},
        "first_folder_id": 20,
    }
    with pytest.raises(ValueError, match="Active layer"):
        encode_layers([layer], [], active_layer_id=2, **kwargs)

    folder = LayerFolder(name="Bad", child_layer_ids=[2])
    with pytest.raises(ValueError, match="unknown layer"):
        encode_layers([layer], [folder], active_layer_id=1, **kwargs)


def test_layer_folder_rejects_incomplete_id_allocation() -> None:
    with pytest.raises(ValueError, match="allocation is incomplete"):
        _encode_folder(LayerFolder(name="Folder"), {}, iter(()))


@pytest.mark.parametrize(
    ("layers", "layer_map", "material_map", "message"),
    [
        ([Layer(id=0, name="A")], {0: 18}, {0: 19}, "IDs must be positive"),
        (
            [Layer(id=1, name="A"), Layer(id=1, name="B")],
            {1: 18},
            {1: 19},
            "IDs must be positive",
        ),
        ([Layer(id=1, name="")], {1: 18}, {1: 19}, "names must be non-empty"),
        (
            [Layer(id=1, name="A"), Layer(id=2, name="A")],
            {1: 18, 2: 20},
            {1: 19, 2: 21},
            "names must be non-empty",
        ),
        ([Layer(id=1, name="A")], {}, {1: 19}, "ID map does not cover"),
        ([Layer(id=1, name="A")], {1: 18}, {}, "material ID map does not cover"),
        (
            [Layer(id=1, name="A", page_behavior=-1)],
            {1: 18},
            {1: 19},
            "page behavior must fit",
        ),
    ],
)
def test_layers_reject_invalid_identity_and_scalars(
    layers: list[Layer],
    layer_map: dict[int, int],
    material_map: dict[int, int],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        encode_layers(
            layers,
            [],
            layer_id_map=layer_map,
            display_material_id_map=material_map,
            first_folder_id=20,
            active_layer_id=None,
        )
