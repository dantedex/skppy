# SPDX-License-Identifier: MIT
"""Raw SU2017 face texture-coordinate writer fixtures."""

import struct

import pytest

import skppy
from skppy.legacy_writter import build_legacy_2017_model


def test_face_uv_matches_raw_sdk_attribute_container_payload() -> None:
    model = skppy.Model.new()
    face = model.entities.add_face([(0, 0, 0), (20, 0, 0), (20, 20, 0), (0, 20, 0)])
    face.front_uv = skppy.FaceUVProjection(transform=[10, 0, 0, 0, 20, 0, 0, 0, 1], origin=(0, 0, 0))
    expected = bytes.fromhex("0380000000ffff04001200") + b"CFaceTextureCoords" + bytes(7)
    expected += struct.pack("<12d", 10, 0, 0, 0, 20, 0, 0, 0, 1, 0, 0, 0)
    expected += struct.pack("<12d", 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0)
    expected += struct.pack("<IIII", 0, 0, 1, 0) + bytes(2)

    encoded = build_legacy_2017_model(model)

    assert expected in encoded


def test_writes_front_and_back_uv_pins_and_projection_flags() -> None:
    model = skppy.Model.new()
    face = model.entities.add_face([(0, 0, 0), (1, 0, 0), (0, 1, 0)])
    pin = skppy.UVPin(skppy.Vector2D(0.25, 0.5), skppy.Vector2D(10, 20))
    face.front_uv = skppy.FaceUVProjection(pins=[pin], projection_direction=(0, -1, 0))
    face.back_uv = skppy.FaceUVProjection(pins=[pin])

    encoded = build_legacy_2017_model(model)

    expected_pin = struct.pack("<I4d", 1, 0.25, 0.5, 10.0, 20.0)
    assert encoded.count(expected_pin) == 2
    assert struct.pack("<II", 3, 1) in encoded
    assert struct.pack("<3d", 0, -1, 0) in encoded


def test_rejects_invalid_uv_transform_length() -> None:
    model = skppy.Model.new()
    face = model.entities.add_face([(0, 0, 0), (1, 0, 0), (0, 1, 0)])
    face.front_uv = skppy.FaceUVProjection(transform=[1.0, 0.0])

    with pytest.raises(ValueError, match="nine values"):
        build_legacy_2017_model(model)
