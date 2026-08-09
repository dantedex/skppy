# SPDX-License-Identifier: MIT
import struct

import pytest

from skppy import Watermark, WatermarkManager
from skppy.writer.watermarks import encode_watermark_manager, watermark_entries


def _raw_record(tag: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HI", tag, len(payload)) + payload


def test_empty_watermark_manager_matches_raw_tlv_bytes() -> None:
    expected = _raw_record(
        0x2CEC,
        _raw_record(0x2CED) + _raw_record(0x2CEE, struct.pack("<i", 0)),
    )

    assert encode_watermark_manager(WatermarkManager()) == expected


def test_watermark_manager_matches_raw_tlv_bytes() -> None:
    image = b"\x89PNG\r\n\x1a\nraw"
    dib = _raw_record(
        0x2328,
        _raw_record(0x2329, struct.pack("<i", 4)) + _raw_record(0x232A, b"watermarks/Overlay.png"),
    )
    watermark = b"".join(
        (
            _raw_record(0x05DC, _raw_record(0x05DE, b"\x01")),
            _raw_record(0x2EE1),
            _raw_record(0x2EE2, b"\x00"),
            _raw_record(0x2EE3, struct.pack("<i", 0)),
            _raw_record(0x2EE4, b"Overlay"),
            _raw_record(0x2EE5, struct.pack("<i", 4)),
            _raw_record(0x2EE6, dib),
            _raw_record(0x2EE7, b"\x01"),
            _raw_record(0x2EE8, b"\x00"),
            _raw_record(0x2EE9, b"\x00"),
            _raw_record(0x2EEE, struct.pack("<i", 0)),
            _raw_record(0x2EEF, struct.pack("<i", 0)),
            _raw_record(0x2EEA, b"\x00"),
            _raw_record(0x2EEB, struct.pack("<d", 0.5)),
            _raw_record(0x2EEC, b"\x01"),
            _raw_record(0x2EED, struct.pack("<d", 0.75)),
        )
    )
    expected = _raw_record(
        0x2CEC,
        _raw_record(0x2CED, _raw_record(0x2EE0, watermark)) + _raw_record(0x2CEE, struct.pack("<I", 1)),
    )

    manager = WatermarkManager(
        watermarks=[Watermark(name="Overlay", image_data=image, opacity=0.75, position=5)],
        serialized_count=1,
    )
    assert encode_watermark_manager(manager) == expected


def test_jpeg_watermark_matches_raw_quality_and_resource_bytes() -> None:
    mark = Watermark(id=7, name="Photo", image_data=b"\xff\xd8raw", position=2)
    manager = WatermarkManager(watermarks=[mark])
    encoded = encode_watermark_manager(manager, {7: 18})

    assert _raw_record(0x05DE, b"\x12") in encoded
    assert _raw_record(0x2329, struct.pack("<i", 1)) in encoded
    assert _raw_record(0x232A, b"watermarks/Photo.jpg") in encoded
    assert _raw_record(0x232C, struct.pack("<i", 90)) in encoded
    assert watermark_entries(manager) == {"watermarks/Photo.jpg": b"\xff\xd8raw"}
    assert watermark_entries(None) == {}


@pytest.mark.parametrize(
    ("mark", "message"),
    [
        (Watermark(name="", image_data=b"\xff\xd8"), "names must be non-empty"),
        (
            Watermark(name="bad/name", image_data=b"\xff\xd8"),
            "names must be path-safe",
        ),
        (Watermark(name="Bad"), "require image data"),
        (
            Watermark(name="Bad", image_data=b"\xff\xd8", opacity=2.0),
            "opacity must be between",
        ),
        (
            Watermark(name="Bad", image_data=b"\xff\xd8", position=6),
            "position must be between",
        ),
        (
            Watermark(name="Bad", image_data=b"invalid"),
            "must be PNG or JPEG",
        ),
    ],
)
def test_watermarks_reject_unrepresentable_values(mark: Watermark, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        encode_watermark_manager(WatermarkManager(watermarks=[mark]))


def test_watermark_manager_and_resources_reject_inconsistent_lists() -> None:
    with pytest.raises(ValueError, match="count must match"):
        encode_watermark_manager(WatermarkManager(serialized_count=1))

    missing = Watermark(name="Missing")
    with pytest.raises(ValueError, match="require image data"):
        watermark_entries(WatermarkManager(watermarks=[missing]))

    first = Watermark(name="Same", image_data=b"\xff\xd8one")
    second = Watermark(name="Same", image_data=b"\xff\xd8two")
    with pytest.raises(ValueError, match="Duplicate"):
        watermark_entries(WatermarkManager(watermarks=[first, second]))
