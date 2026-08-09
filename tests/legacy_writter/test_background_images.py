# SPDX-License-Identifier: MIT
"""Raw SU2017 match-photo background-image writer fixtures."""

import pytest

import skppy
from skppy.legacy_writter import build_legacy_2017_model
from skppy.legacy_writter.model import _LegacyModelEncoder


def test_background_image_matches_raw_carchive_payload_and_reuses_its_object() -> None:
    model = skppy.Model.new()
    image = skppy.PageBackgroundImage(
        id=5,
        path="p.png",
        reference_state=1,
        image_data=b"PNG",
        width=2,
        height=3,
        file_size=3,
        timestamp=4,
        visible=True,
        opacity=0.5,
        grip_points=[skppy.Vector3D(1, 2, 3)],
        principal_point_delta=skppy.Vector3D(4, 5, 6),
        radial_distortion_k1=0.1,
        image_source=2,
    )
    encoder = _LegacyModelEncoder(model, model.entities)
    encoder.data.clear()
    encoder._write_background_image_reference(image)
    expected = bytes.fromhex(
        "ffff0a001000434261636b67726f756e64496d61676500000105fffeff0570002e0070006e00670001000000ffff0300040043446962040000000300"
        "0000504e470200000003000000030000000400000001000000000000e03f01000000000000000000f03f000000000000004000000000000008400000"
        "000000001040000000000000144000000000000018409a9999999999b93f02000000"
    )

    assert encoder.data == expected

    encoder.data.clear()
    encoder._write_background_image_reference(image)
    assert encoder.data == bytes.fromhex("0a00")


def test_scene_backgrounds_resolve_directly_and_by_public_id() -> None:
    image = skppy.PageBackgroundImage(id=5, path="photo.png", image_data=b"PNG")
    model = skppy.Model.new()
    model.scenes = [
        skppy.Scene(1, "Direct", background_image=image),
        skppy.Scene(2, "Reference", background_image_ref=5),
    ]

    encoded = build_legacy_2017_model(model)

    assert encoded.count(b"CBackgroundImage") == 1


@pytest.mark.parametrize(
    ("image", "message"),
    [
        (skppy.PageBackgroundImage(), "require image data"),
        (skppy.PageBackgroundImage(image_data=b"PNG", width=-1), "integer fields must fit"),
        (skppy.PageBackgroundImage(image_data=b"PNG", opacity=2.0), "opacity must be between"),
    ],
)
def test_rejects_invalid_background_images(image: skppy.PageBackgroundImage, message: str) -> None:
    model = skppy.Model.new()
    model.background_image = image

    with pytest.raises(ValueError, match=message):
        build_legacy_2017_model(model)
