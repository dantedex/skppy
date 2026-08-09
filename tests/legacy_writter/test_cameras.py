# SPDX-License-Identifier: MIT
"""Raw SU2017 current-camera writer fixtures."""

import pytest

import skppy
from skppy.legacy_writter.envelope import _camera_body
from skppy.legacy_writter.model import build_legacy_2017_model


def test_camera_matches_raw_sdk_carchive_payload() -> None:
    camera = skppy.Camera(
        eye=skppy.Vector3D(1, 2, 3),
        target=skppy.Vector3D(4, 5, 6),
        up=skppy.Vector3D(0, 0, 1),
        fov=42.5,
        fov_is_height=False,
        is_perspective=False,
        near=0.25,
        far=900,
        name="Main",
        ortho_height=25,
        aspect_ratio=1.5,
        legacy_flag=True,
        image_width=1920,
        is_2d=True,
        scale_2d=2,
        center_2d_x=-3,
        center_2d_y=4,
    )
    expected = bytes.fromhex(
        "000000000000f03f00000000000000400000000000000840000000000000104000000000000014400000000000001840"
        "00000000000000000000000000000000000000000000f03f000000000000d03f0000000000208c400000000000004045"
        "400000000000003940000000000000000000000000000000000000000000000000000000000000f83f0001fffeff044d"
        "00610069006e000000000000009e4001000000000000004000000000000008c00000000000001040"
    )

    assert _camera_body(camera) == expected


def test_legacy_model_rejects_multiple_current_cameras() -> None:
    model = skppy.Model.new()
    model.cameras.extend((skppy.Camera(), skppy.Camera()))

    with pytest.raises(ValueError, match="only one current camera"):
        build_legacy_2017_model(model)
