# SPDX-License-Identifier: MIT
"""Raw-byte checks for modern camera serialization."""

from __future__ import annotations

import struct

import pytest

from skppy.data_structure.construction import Camera
from skppy.data_structure.primitives import Vector3D
from skppy.writer.cameras import encode_camera_record, encode_cameras


def _raw_record(tag: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HI", tag, len(payload)) + payload


def _camera() -> Camera:
    return Camera(
        eye=Vector3D(100, 100, 100),
        target=Vector3D(0, 0, 0),
        up=Vector3D(0, 0, 1),
        near=1.0,
        far=1000.0,
        is_perspective=True,
        fov=30.0,
        ortho_height=133.0,
        aspect_ratio=0.0,
        fov_is_height=True,
        legacy_flag=False,
        name="Current camera",
        image_width=0.0,
        is_2d=False,
        scale_2d=1.0,
        center_2d_x=0.0,
        center_2d_y=0.0,
        allow_clipping=False,
    )


def test_camera_record_matches_raw_expected_bytes() -> None:
    payload = b"".join(
        (
            _raw_record(0x34BD, struct.pack("<3d", 100, 100, 100)),
            _raw_record(0x34BE, struct.pack("<3d", 0, 0, 0)),
            _raw_record(0x34BF, struct.pack("<3d", 0, 0, 1)),
            _raw_record(0x34C0, struct.pack("<d", 1.0)),
            _raw_record(0x34C1, struct.pack("<d", 1000.0)),
            _raw_record(0x34C2, b"\x01"),
            _raw_record(0x34C4, struct.pack("<d", 30.0)),
            _raw_record(0x34C3, struct.pack("<d", 133.0)),
            _raw_record(0x34C5, struct.pack("<d", 0.0)),
            _raw_record(0x34C6, b"\x01"),
            _raw_record(0x34C7, b"\x00"),
            _raw_record(0x34C8, b"Current camera"),
            _raw_record(0x34C9, struct.pack("<d", 0.0)),
            _raw_record(0x34CA, b"\x00"),
            _raw_record(0x34CB, struct.pack("<d", 1.0)),
            _raw_record(0x34CC, struct.pack("<d", 0.0)),
            _raw_record(0x34CD, struct.pack("<d", 0.0)),
            _raw_record(0x34CE, b"\x00"),
        )
    )
    expected = _raw_record(0x34BC, payload)

    assert encode_camera_record(_camera()) == expected
    assert encode_cameras([_camera()]) == expected


def test_current_camera_block_requires_exactly_one_camera() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        encode_cameras([])


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"near": float("nan")}, "must be finite"),
        ({"eye": Vector3D(0, 0, 0)}, "eye and target must differ"),
        ({"up": Vector3D(0, 0, 0)}, "up vector must be non-zero"),
        ({"near": 0.0}, "0 < near < far"),
        ({"fov": 180.0}, "field of view must be"),
        ({"ortho_height": 0.0}, "orthographic height must be positive"),
        ({"aspect_ratio": -1.0}, "aspect ratio must be non-negative"),
        ({"image_width": -1.0}, "image width must be non-negative"),
        ({"scale_2d": 0.0}, "2-D scale must be positive"),
        ({"name": "bad\x00camera"}, "cannot contain NUL"),
    ],
)
def test_camera_rejects_unrepresentable_values(changes: dict, message: str) -> None:
    camera = _camera()
    for field, value in changes.items():
        setattr(camera, field, value)
    with pytest.raises(ValueError, match=message):
        encode_camera_record(camera)
