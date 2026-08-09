# SPDX-License-Identifier: MIT
"""Raw SU2017 material and layer writer fixtures."""

import pytest

import skppy
from skppy.legacy_writter import build_legacy_2017_model
from skppy.legacy_writter.model import _encode_legacy_string


def test_material_matches_raw_sdk_object_and_face_reference() -> None:
    model = skppy.Model.new()
    material = model.add_material("RedMaterial", color=skppy.Color(255, 0, 0))
    face = model.entities.add_face([(0, 0, 0), (10, 0, 0), (0, 10, 0)])
    face.front_material_id = material.id
    expected = bytes.fromhex(
        "ffff0c000900434d6174657269616c00000112fffeff0b5200650064004d006100740065007200690061006c000000"
        "ff0000fffffeff000000000000000000000000000000e03f00"
    )

    encoded = build_legacy_2017_model(model)

    assert expected in encoded
    face_start = encoded.index(b"CFace") + len(b"CFace")
    assert encoded[face_start : face_start + 8] == bytes.fromhex("000001130a000001")


def test_layers_match_raw_sdk_objects_and_entity_references() -> None:
    model = skppy.Model.new()
    walls = model.add_layer("Writer Walls")
    roof = model.add_layer("Writer Roof", visible=False)
    walls.material = skppy.Material(id=100, name="Writer Layer Color", color=skppy.Color(10, 20, 30))
    model.active_layer_id = roof.id
    face = model.entities.add_face([(0, 0, 0), (2, 0, 0), (0, 2, 0)])
    face.layer_id = walls.id
    model.entities.edges[0].layer_id = roof.id
    expected_walls = bytes.fromhex(
        "098000000112fffeff0c5700720069007400650072002000570061006c006c007300000000"
        "0113fffeff1257007200690074006500720020004c006100790065007200200043006f006c006f00720000010a141e"
        "fffffeff000000000000000000000000000000e03f0000000000"
    )

    encoded = build_legacy_2017_model(model)

    assert expected_walls in encoded
    assert bytes.fromhex("098000000114fffeff0b") in encoded  # Reused CLayer class, hidden roof body.
    face_start = encoded.index(b"CFace") + len(b"CFace")
    assert encoded[face_start : face_start + 14].endswith(bytes.fromhex("0b00"))
    assert bytes.fromhex("ffff0200050043456467650000011700000001010000000c00") in encoded


def test_writes_material_transparency_and_long_legacy_strings() -> None:
    model = skppy.Model.new()
    model.add_material("Transparent", color=skppy.Color(1, 2, 3, 4), alpha=0.25)

    encoded = build_legacy_2017_model(model)

    assert bytes.fromhex("01020304") in encoded
    assert bytes.fromhex("000000000000e83f01") in encoded
    assert _encode_legacy_string("x" * 255).startswith(bytes.fromhex("fffeffffff00"))
    assert _encode_legacy_string("x" * 65535).startswith(bytes.fromhex("fffeffffffffffff0000"))


def test_texture_matches_raw_sdk_inline_texture_and_dib_layout() -> None:
    model = skppy.Model.new()
    material = model.add_material("Texture", color=skppy.Color(10, 20, 30))
    material.has_texture = True
    material.texture = skppy.Texture(
        filename="one.png",
        x_scale=2.0,
        y_scale=3.0,
        data=b"\x89PNG\r\n\x1a\n",
    )
    expected = bytes.fromhex(
        "000000ffff0300040043446962040000000800000089504e470d0a1a0a00000000000000400000000000000840"
        "fffeff076f006e0065002e0070006e0067000a141eff"
    )

    encoded = build_legacy_2017_model(model)

    assert expected in encoded


def test_rejects_missing_resource_references() -> None:
    missing_material = skppy.Model.new()
    face = missing_material.entities.add_face([(0, 0, 0), (1, 0, 0), (0, 1, 0)])
    face.back_material_id = 99
    with pytest.raises(ValueError, match="missing material ID 99"):
        build_legacy_2017_model(missing_material)

    missing_layer = skppy.Model.new()
    vertices = [missing_layer.entities.add_vertex(index, 0, 0) for index in range(2)]
    missing_layer.entities.add_edge(*vertices).layer_id = 99
    with pytest.raises(ValueError, match="missing layer ID 99"):
        build_legacy_2017_model(missing_layer)

    missing_layer.active_layer_id = 99
    with pytest.raises(ValueError, match="missing active layer ID 99"):
        build_legacy_2017_model(missing_layer)


def test_rejects_materials_with_inconsistent_texture_data() -> None:
    missing_texture = skppy.Model.new()
    missing_texture.add_material("Texture").has_texture = True
    with pytest.raises(ValueError, match="declares a missing texture"):
        build_legacy_2017_model(missing_texture)

    missing_data = skppy.Model.new()
    missing_data.add_material("Texture").texture = skppy.Texture(filename="missing.png")
    with pytest.raises(ValueError, match="no embedded image data"):
        build_legacy_2017_model(missing_data)
