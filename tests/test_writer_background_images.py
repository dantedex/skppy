# SPDX-License-Identifier: MIT
"""Raw-byte checks for modern match-photo image serialization."""

import struct

import pytest

from skppy import PageBackgroundImage, Vector3D
from skppy.writer.background_images import (
    background_image_entries,
    encode_background_images,
)


def _raw_record(tag: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HI", tag, len(payload)) + payload


def test_background_image_matches_raw_expected_bytes() -> None:
    image_data = b"\x89PNG\r\n\x1a\nraw"
    image = PageBackgroundImage(
        path="writer.png",
        reference_state=2,
        image_data=image_data,
        width=1,
        height=1,
        file_size=10,
        timestamp=123,
        visible=True,
        opacity=0.6,
        grip_points=[Vector3D(1.0, 2.0, 3.0)],
        principal_point_delta=Vector3D(0.1, 0.2, 0.3),
        radial_distortion_k1=0.01,
        image_source=1,
    )
    dib = _raw_record(
        0x2328,
        _raw_record(0x2329, struct.pack("<i", 4)) + _raw_record(0x232A, b"matched_photos/writer.png"),
    )
    image_reference = _raw_record(
        0x2AF8,
        b"".join(
            (
                _raw_record(0x2AF9, b"writer.png"),
                _raw_record(0x2AFA, struct.pack("<i", 2)),
                _raw_record(0x2AFB, dib),
                _raw_record(0x2AFC, struct.pack("<i", 1)),
                _raw_record(0x2AFD, struct.pack("<i", 1)),
                _raw_record(0x2AFE, struct.pack("<i", 10)),
                _raw_record(0x2AFF, struct.pack("<i", 123)),
            )
        ),
    )
    expected_payload = b"".join(
        (
            _raw_record(0x05DC, _raw_record(0x05DE, b"\x12")),
            _raw_record(0x2905, image_reference),
            _raw_record(0x2906, b"\x01"),
            _raw_record(0x2907, struct.pack("<d", 0.6)),
            _raw_record(0x2908, struct.pack("<ddd", 1.0, 2.0, 3.0)),
            _raw_record(0x2909, struct.pack("<ddd", 0.1, 0.2, 0.3)),
            _raw_record(0x290A, struct.pack("<d", 0.01)),
            _raw_record(0x290B, struct.pack("<i", 1)),
        )
    )

    assert encode_background_images([image], {id(image): 18}) == _raw_record(0x2904, expected_payload)
    assert background_image_entries([image]) == {"matched_photos/writer.png": image_data}


def test_jpeg_background_emits_raw_quality_and_canonical_extension() -> None:
    image = PageBackgroundImage(path="photo.jpeg", image_data=b"\xff\xd8raw")
    encoded = encode_background_images([image], {id(image): 18})

    assert _raw_record(0x2329, struct.pack("<i", 1)) in encoded
    assert _raw_record(0x232A, b"matched_photos/photo.jpg") in encoded
    assert _raw_record(0x232C, struct.pack("<i", 90)) in encoded
    assert background_image_entries([image]) == {"matched_photos/photo.jpg": b"\xff\xd8raw"}


def test_background_resources_reject_missing_and_duplicate_data() -> None:
    with pytest.raises(ValueError, match="require image data"):
        background_image_entries([PageBackgroundImage(path="missing.png")])

    first = PageBackgroundImage(path="same.png", image_data=b"\x89PNG\r\n\x1a\n1")
    second = PageBackgroundImage(path="folder/same.png", image_data=b"\x89PNG\r\n\x1a\n2")
    with pytest.raises(ValueError, match="Duplicate"):
        background_image_entries([first, second])


@pytest.mark.parametrize(
    ("image", "message"),
    [
        (PageBackgroundImage(path="none.png"), "require image data"),
        (
            PageBackgroundImage(path="bad.bin", image_data=b"invalid"),
            "must be PNG or JPEG",
        ),
        (
            PageBackgroundImage(path="bad.png", image_data=b"\x89PNG\r\n\x1a\n", opacity=1.5),
            "opacity must be between",
        ),
        (
            PageBackgroundImage(
                path="bad.png",
                image_data=b"\x89PNG\r\n\x1a\n",
                width=2**31,
            ),
            "width must fit in i32",
        ),
        (
            PageBackgroundImage(path=".jpg", image_data=b"\xff\xd8raw"),
            "path-safe file name",
        ),
    ],
)
def test_background_images_reject_unrepresentable_values(image: PageBackgroundImage, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        encode_background_images([image], {id(image): 18})
