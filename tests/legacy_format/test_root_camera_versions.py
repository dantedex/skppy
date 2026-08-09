# SPDX-License-Identifier: MIT
"""Root-camera layouts selected by the pre-ZIP model schema."""

from __future__ import annotations

import io
import struct

from skppy.parser_legacy.camera_payloads import read_root_camera_section

from ._fixtures import _camera_payload_bytes, _new_class_tag


def test_root_camera_before_model_v21_has_no_leading_dib_tag() -> None:
    """Model schemas 11-20 serialize only the tagged camera object."""
    data = _new_class_tag("CCamera", schema=4) + _camera_payload_bytes(4)

    leading, camera_tag, camera, end, dib = read_root_camera_section(
        io.BytesIO(data),
        model_class_version=12,
        camera_class_version=4,
    )

    assert leading.kind == "null"
    assert camera_tag.class_name == "CCamera"
    assert camera.eye.to_tuple() == (10.0, 20.0, 30.0)
    assert end == len(data)
    assert dib is None


def test_sketchup3_root_camera_uses_untagged_old_layout() -> None:
    """Model schemas below 11 store eye plus direction without CCamera tags."""
    data = b"".join(
        [
            struct.pack("<3d", 10.0, 20.0, 30.0),
            struct.pack("<3d", 0.0, 0.0, -1.0),
            struct.pack("<3d", 0.0, 1.0, 0.0),
            struct.pack("<2d", 1.0, 1000.0),
            b"\x01",
            struct.pack("<2d", 0.5, 10.0),
            struct.pack("<3d", 0.0, 0.0, 0.0),
        ]
    )

    leading, camera_tag, camera, end, dib = read_root_camera_section(
        io.BytesIO(data),
        model_class_version=10,
        camera_class_version=None,
    )

    assert leading.kind == camera_tag.kind == "null"
    assert camera.eye.to_tuple() == (10.0, 20.0, 30.0)
    assert camera.target.to_tuple() == (10.0, 20.0, 29.0)
    assert end == len(data)
    assert dib is None
